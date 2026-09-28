"""把 SemIf（开源版 Jev）的判定引擎接到「八艺」这八个字上。

引擎本身来自 ``vendor/SemIf-OpenJev``（MIT），这里**不修改上游代码**，
只是：

1. 用中文重写 system prompt（上游是英文），结构完全一致；
2. 复用上游的判定机制 —— 每个选项绑定一个单 token 的大写字母槽位，
   一次 forward 只取最后一个位置的 logits，再对这几个槽位做 softmax；
3. 把结果映射回八个字。

核心事实：**模型不生成任何文字**。它只在一次前向传播里，把「下一个 token
是 A / B / C …」的概率读出来。所以小模型也能做到百毫秒级响应。
"""

from __future__ import annotations

import json
import random
import sys
import threading
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENDOR_SRC = PROJECT_ROOT / "vendor" / "SemIf-OpenJev" / "src"

#: 默认基座：Qwen3.5-2B。
#: 留出集实测 87%，中位 ~90 ms（0.6B 是 63%，4B 更准但体积翻倍）。
#: 选它的理由就是「小一点、快一点，同时够用」。
DEFAULT_MODEL_DIR = PROJECT_ROOT / "models" / "Qwen3.5-2B"
DEFAULT_REVISION = "15852e8c16360a2fea060d615a32b45270f8a8fc"

#: 备选基座（体积 / 实测准确率见 docs/EVAL.md）。
MODEL_CHOICES: dict[str, tuple[str, str]] = {
    "qwen3-0.6b": ("Qwen3-0.6B", "c1899de289a04d12100db370d81485cdf75e47ca"),
    "qwen3.5-2b": ("Qwen3.5-2B", "15852e8c16360a2fea060d615a32b45270f8a8fc"),
    "qwen3.5-4b": ("Qwen3.5-4B", "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"),
}

#: 一次判定最多吃多少 token（上游语义：超限直接报错，绝不截断）。
MAX_TOKENS = 4096

if str(VENDOR_SRC) not in sys.path:
    sys.path.insert(0, str(VENDOR_SRC))

from semif_phase1.core import (  # noqa: E402  (需要先插 sys.path)
    LETTERS,
    load_causal_model,
    softmax,
    synchronize,
)
from semif_phase1.direct import _forward, _slot_ids  # noqa: E402

from .labels import (
    CRITERION,
    LABELS_BY_ID,
    MEME_LABELS,
)
from .profiles import Profile

#: 与上游 ``core.DIRECT_SYSTEM`` 一一对应的中文版。
DIRECT_SYSTEM_ZH = (
    "请根据给定的判断标准，对给定的文本证据做出判断，从列出的选项中选出唯一最符合的一项。"
    "只回答该项对应的大写字母，不要解释，不要推理。"
)

PROMPT_VERSION = "meme-direct-zh-v4"

#: 默认参与平均的选项排列数。
#: 实测（120 条真实评论）：1 个排列只剩 53%~87% 且会塌缩到某个词、3 个 82.5%、
#: 5 个 91.7%、7 个 91.7%。排列越多结果越稳（单排列只有 63% 的样本换顺序后答案不变）。
#: 因为这些排列共享同一段文本，可以并成一个 batch 跑，代价远低于跑 N 次。
DEFAULT_PERMUTATIONS = 5


def permutations_of(
    labels: list[dict[str, str]], count: int, seed: int = 0
) -> list[list[dict[str, str]]]:
    """生成 ``count`` 种选项排列：原始顺序 + 完全反转 + 若干随机排列。

    固定 seed，保证同一个输入永远得到同一个答案（可复现）。
    """
    if count <= 1:
        return [list(labels)]
    orders = [list(labels), list(reversed(labels))]
    rng = random.Random(seed)
    while len(orders) < count:
        candidate = list(labels)
        rng.shuffle(candidate)
        orders.append(candidate)
    return orders[:count]


#: 批量前向的「token 预算」：排列数 × prompt 长度不超过这个量级。
#:
#: 注意 prompt 本身就不短 —— 八个字的锚点例句加起来约 950 token，
#: 所以**哪怕评论只有一句话，prompt 也有 1000 token 左右**。
#: 预算要足够大，页面上三档才都是真档位（否则「更稳」会被悄悄压成 5）。
#: 设成 7500 的实际效果：
#:   1000 token（普通评论）+ 快/标准/更稳 -> 3 / 5 / 7 个排列
#:   2000 token（长评论）                 -> 3 个排列
#:   4000 token（接近上限）               -> 1 个排列
#: 这样延迟基本被压在同一个量级，不会随输入长度线性膨胀。
TOKEN_BUDGET = 7500


def adaptive_permutations(tokens: int, requested: int, budget: int = TOKEN_BUDGET) -> int:
    """按 prompt 长度把排列数压到预算内。

    排列平均的收益在短文本上最划算；输入一长，前向本身就慢，再乘 N 倍就没意义了。
    """
    if requested <= 1:
        return 1
    return max(1, min(requested, budget // max(tokens, 1)))


def pick_device(preference: str = "auto") -> str:
    """挑一个上游 ``resolve_device`` 认得的设备字符串。

    上游的 ``auto`` 会退到 MPS，在 Windows 上会直接抛错，所以这里自己判。
    """
    import torch

    if preference == "cpu":
        return "cpu"
    if preference == "cuda":
        if not torch.cuda.is_available():
            raise RuntimeError("指定了 cuda，但当前 torch 看不到可用的 CUDA 设备")
        return "cuda"
    return "cuda" if torch.cuda.is_available() else "cpu"


def _messages(evidence: str, criterion: str, options: list[dict[str, str]]) -> list[dict[str, str]]:
    """复刻上游 ``direct_messages`` 的 payload 结构，只把 system 换成中文。"""
    payload = {
        "evidence": evidence,
        "criterion": criterion,
        "options": [
            {"letter": LETTERS[index], "description": option["description"]}
            for index, option in enumerate(options)
        ],
    }
    return [
        {"role": "system", "content": DIRECT_SYSTEM_ZH},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


class MemeJev:
    """常驻内存的八艺判定器：加载一次，之后每次判定只要一次 forward。"""

    def __init__(
        self,
        model_dir: str | Path = DEFAULT_MODEL_DIR,
        revision: str = DEFAULT_REVISION,
        device: str = "auto",
    ) -> None:
        self.model_dir = Path(model_dir)
        self.revision = revision
        self.device_preference = device
        self._lock = threading.Lock()
        self._model = None
        self._tokenizer = None
        self.metadata: dict[str, Any] = {}
        self.load_seconds: float | None = None

    # ---------------------------------------------------------------- 加载

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self.loaded:
            return
        if not self.model_dir.exists():
            raise FileNotFoundError(
                f"本地模型不存在：{self.model_dir}\n"
                f"先跑：python scripts/download_model.py"
            )
        target = pick_device(self.device_preference)
        dtype = "bfloat16" if target == "cuda" else "float32"
        started = time.perf_counter()
        model, tokenizer, metadata = load_causal_model(
            source=str(self.model_dir),
            revision=self.revision,
            device=target,
            dtype=dtype,
        )
        self._model, self._tokenizer = model, tokenizer
        self.load_seconds = time.perf_counter() - started
        self.metadata = {
            **metadata,
            "model_dir": str(self.model_dir),
            "prompt_version": PROMPT_VERSION,
        }
        # 先跑一次，把 CUDA kernel 编译 / 显存分配的开销挪出首次请求。
        self.warmup()

    def warmup(self) -> None:
        """预热：把 CUDA kernel 编译 / 显存分配的开销挪出首次请求。

        刻意用**默认排列数的批量前向**来热，保证第一次真实请求就是热的。
        """
        option_sets = permutations_of(MEME_LABELS, DEFAULT_PERMUTATIONS)
        self._readout_many(
            "预热", CRITERION, [[dict(label) for label in order] for order in option_sets]
        )

    # ------------------------------------------------------------ 判定核心

    def _build_prompt(
        self,
        evidence: str,
        criterion: str,
        options: list[dict[str, str]],
    ) -> tuple[list[int], list[int]]:
        """把一次判定编成一个 prompt，并校验答案槽位干净。"""
        tokenizer = self._tokenizer
        assert tokenizer is not None

        prompt = tokenizer.apply_chat_template(
            _messages(evidence, criterion, options),
            tokenize=False,
            add_generation_prompt=True,
            enable_thinking=False,
        )
        ids = tokenizer.encode(prompt, add_special_tokens=False)
        if not ids or len(ids) > MAX_TOKENS:
            raise ValueError(
                f"输入 {len(ids)} token，超过上限 {MAX_TOKENS}；按上游约定不做截断"
            )

        slots = _slot_ids(tokenizer, len(options))
        # 保证「prompt + 字母」不会把字母并进别的 token —— 槽位必须干净。
        for letter, token in zip(LETTERS, slots):
            if tokenizer.encode(prompt + letter, add_special_tokens=False) != ids + [token]:
                raise ValueError(f"选项槽位 {letter} 的 token 边界不稳定")
        return ids, slots

    def _readout_many(
        self,
        evidence: str,
        criterion: str,
        option_sets: list[list[dict[str, str]]],
    ) -> dict[str, Any]:
        """对同一段文本的**多个选项排列**做一次批量前向。

        为什么要多个排列：Jev 读的是「下一个 token 是哪个字母」，而模型对字母位置
        本身有偏好。实测同一条文本只换选项顺序，准确率能在 70%~80% 之间摆动，
        只有 63% 的样本在五种排列下答案一致。多个排列取平均可以把这个位置噪声压掉，
        而且因为所有排列共享同一段文本，可以塞进一个 batch 里跑，代价远低于跑 N 次。
        """
        import torch

        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError("待判定的文本不能为空")

        tokenizer, model = self._tokenizer, self._model
        assert tokenizer is not None and model is not None

        built = []
        for options in option_sets:
            if not 2 <= len(options) <= len(LETTERS):
                raise ValueError(f"选项数量必须在 2 到 {len(LETTERS)} 之间")
            built.append(self._build_prompt(evidence, criterion, options))

        width = max(len(ids) for ids, _ in built)
        pad_id = tokenizer.pad_token_id
        if pad_id is None:
            pad_id = tokenizer.eos_token_id
        # 左填充：这样每一行最后一个位置都是真实的最后一个 token。
        input_ids, attention_mask = [], []
        for ids, _ in built:
            pad = width - len(ids)
            input_ids.append([pad_id] * pad + ids)
            attention_mask.append([0] * pad + [1] * len(ids))

        device = next(model.parameters()).device
        inputs = {
            "input_ids": torch.tensor(input_ids, dtype=torch.long, device=device),
            "attention_mask": torch.tensor(attention_mask, dtype=torch.long, device=device),
        }
        synchronize(device)
        forward_start = time.perf_counter()
        with torch.inference_mode():
            vocabulary = _forward(model, inputs).float()  # (batch, vocab)
        synchronize(device)
        forward_seconds = time.perf_counter() - forward_start

        rows = []
        for index, (_, slots) in enumerate(built):
            logits = vocabulary[index][slots].cpu().tolist()
            rows.append({"probabilities": softmax(logits), "option_logits": logits})

        return {
            "rows": rows,
            "input_tokens": max(len(ids) for ids, _ in built),
            "batch": len(built),
            "forward_seconds": forward_seconds,
        }

    def _readout(
        self,
        evidence: str,
        criterion: str,
        options: list[dict[str, str]],
    ) -> dict[str, Any]:
        """单次前向读出各选项槽位上的概率（= 只有一个排列的批量前向）。"""
        result = self._readout_many(evidence, criterion, [options])
        return {**result["rows"][0], "input_tokens": result["input_tokens"],
                "forward_seconds": result["forward_seconds"]}

    # ---------------------------------------------------------------- 对外

    def choose(
        self,
        text: str,
        labels: list[dict[str, str]],
        criterion: str | None = None,
        permutations: int = DEFAULT_PERMUTATIONS,
    ) -> dict[str, Any]:
        """通用判定：给定任意标签集，选最贴切的一个。

        标签描述是运行时数据，所以换一套标签不需要动模型 —— 实验脚本也走这条路。

        ``permutations`` 是参与平均的选项排列数。设成 1 就是最原始的单次判定
        （最快，但有位置噪声）；大于 1 会把位置偏置平均掉，代价是一次批量前向。

        输入很长时会自动下调排列数（见 ``adaptive_permutations``），
        免得延迟随长度线性膨胀。实际用了几个排列看返回值里的 ``permutations``。
        """
        if criterion is None:
            # 原来这里写的是 `default_profile().criterion` —— 那个名字从来没定义过，
            # 只是所有调用点都显式传了 criterion 才没炸。默认值就是「八艺」的问法。
            criterion = CRITERION
        option_sets = permutations_of(labels, permutations)
        with self._lock:
            self.load()
            started = time.perf_counter()
            # 先量一下 prompt 有多长，再决定真的跑几个排列。
            probe_ids, _ = self._build_prompt(
                text, criterion, [dict(label) for label in option_sets[0]]
            )
            effective = adaptive_permutations(len(probe_ids), permutations)
            option_sets = option_sets[:effective]
            raw = self._readout_many(
                text, criterion, [[dict(label) for label in order] for order in option_sets]
            )
            total_seconds = time.perf_counter() - started

        # 把每个排列的概率按标签 id 累加，再平均 —— 结果与选项顺序无关。
        totals: dict[str, float] = {label["id"]: 0.0 for label in labels}
        logits: dict[str, float] = {label["id"]: 0.0 for label in labels}
        for order, row in zip(option_sets, raw["rows"]):
            for label, probability, logit in zip(
                order, row["probabilities"], row["option_logits"]
            ):
                totals[label["id"]] += probability / len(option_sets)
                logits[label["id"]] += logit / len(option_sets)

        meta = {label["id"]: label for label in labels}
        ranking = sorted(
            (
                {
                    "id": label_id,
                    "pinyin": meta[label_id].get("pinyin", ""),
                    "hint": meta[label_id].get("hint", ""),
                    "accent": meta[label_id].get("accent", "#8b95ab"),
                    "probability": probability,
                    "logit": logits[label_id],
                }
                for label_id, probability in totals.items()
            ),
            key=lambda item: item["probability"],
            reverse=True,
        )
        return {
            "mode": "choice",
            "winner": ranking[0]["id"],
            "confidence": ranking[0]["probability"],
            "margin": ranking[0]["probability"] - ranking[1]["probability"],
            "ranking": ranking,
            "input_tokens": raw["input_tokens"],
            "permutations": len(option_sets),
            "permutations_requested": permutations,
            "batch": raw["batch"],
            "forward_ms": round(raw["forward_seconds"] * 1000, 2),
            "total_ms": round(total_seconds * 1000, 2),
            "model": self.metadata.get("source", ""),
            "device": self.metadata.get("device", ""),
            "prompt_version": PROMPT_VERSION,
        }

    def decide(
        self,
        text: str,
        permutations: int = DEFAULT_PERMUTATIONS,
        profile: Profile | None = None,
    ) -> dict[str, Any]:
        """判定：这段文本该用哪个选项回。

        ``profile`` 为 ``None`` 时用内置的「八艺」；传一个 ``Profile`` 就是任意
        一套自定义判断类型 —— 换类型不需要动模型，锚点本来就是运行时读进去的。
        """
        if profile is None:
            return self.choose(text, MEME_LABELS, CRITERION, permutations)

        result = self.choose(text, profile.labels, profile.criterion, permutations)
        result["profile"] = profile.id
        result["profile_name"] = profile.name
        result["profile_version"] = profile.version
        return result


__all__ = [
    "MemeJev",
    "LABELS_BY_ID",
    "MEME_LABELS",
    "DEFAULT_MODEL_DIR",
    "DEFAULT_REVISION",
    "DEFAULT_PERMUTATIONS",
    "MODEL_CHOICES",
    "TOKEN_BUDGET",
    "adaptive_permutations",
    "permutations_of",
    "pick_device",
]
