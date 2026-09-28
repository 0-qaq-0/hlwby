"""锚点消融实验：找出把判定吸走的那个词。

## 起因

在**真正干净**的 52 条测试集上重测之后（见 `docs/EVAL.md` 第 1 节），
错例长这样：

    ji-2:急->典   ji-4:急->典   le-1:乐->典   le-2:乐->典
    le-5:乐->典   pi-4:批->典   ying-2:赢->典 ma-2:麻->典 ...

**14 个错例里有 11 个都判成了「典」**，而且跨了 5 个不同的标准答案。
一个词把别人全吃掉，说明它不是判得准，是**描述太泛**：

    「这段话在讲道理、分析原因、下判断 —— 一段不长不短的普通论述。」

后半句「一段不长不短的普通论述」几乎对所有中文评论都成立 ——
它不是判别特征，是吸铁石。

## 这个脚本干什么

把「典」的描述换成几个更窄的版本，其余七个字不动，在**同一套干净集**上比准确率。
只改一处、只动一个变量，所以差异能归因到这次改动上。

用法：
    .venv\\Scripts\\python.exe scripts\\anchor_tune.py
    .venv\\Scripts\\python.exe scripts\\anchor_tune.py --perms 5 --only dian
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from jev_meme import DEFAULT_MODEL_DIR, DEFAULT_REVISION, CRITERION, MEME_LABELS, MemeJev  # noqa: E402

DATA = PROJECT_ROOT / "data" / "eval_clean.jsonl"

#: 「典」描述的候选版本。
#:
#: 每个候选只改这一段的措辞，例句保持原样 —— 这样差异只来自那几句话。
DIAN_VARIANTS: dict[str, str] = {
    "shipped": MEME_LABELS[0]["description"],
    # 只删掉那句泛化的形状描述，别的都不动。
    "drop_shape": (
        "这段话在讲道理、分析原因、下判断。"
        "例：「这个行业不景气主要是前几年扩张太快，现在是在还债」"
        "「他这次没考好也正常，平时基础就没打牢」"
        "「说白了就是供需关系变了，跟努力不努力关系不大」"
        "「主要还是从小没教好，家庭教育才是根子」。"
    ),
    # 再窄一档：明确「在解释成因或下结论」，把「讲道理」这种大词也去掉。
    "explain_only": (
        "这段话在解释一件事为什么会这样，或者给一件事下结论、定性。"
        "例：「这个行业不景气主要是前几年扩张太快，现在是在还债」"
        "「他这次没考好也正常，平时基础就没打牢」"
        "「说白了就是供需关系变了，跟努力不努力关系不大」"
        "「主要还是从小没教好，家庭教育才是根子」。"
    ),
    # 反向对照：故意加一句更泛的，验证「越泛越吸」这个假设。
    "wider": (
        "这段话在讲道理、分析原因、下判断，是一段正常的、有内容的发言。"
        "例：「这个行业不景气主要是前几年扩张太快，现在是在还债」"
        "「他这次没考好也正常，平时基础就没打牢」"
        "「说白了就是供需关系变了，跟努力不努力关系不大」"
        "「主要还是从小没教好，家庭教育才是根子」。"
    ),
}


def wilson(hits: int, total: int, z: float = 1.96) -> tuple[float, float]:
    if total == 0:
        return (0.0, 0.0)
    p = hits / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def main() -> None:
    parser = argparse.ArgumentParser(description="锚点消融：谁把判定吸走了")
    parser.add_argument("--perms", type=int, default=5)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in args.data.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    engine = MemeJev(model_dir=args.model_dir, revision=args.revision, device=args.device)
    engine.load()
    print(f"设备 {engine.metadata['device']} | 数据 {args.data.name} | {len(rows)} 条")
    print(f"排列数 {args.perms}\n")

    results: list[tuple[str, int, int, tuple[float, float], dict[str, int]]] = []

    for name, description in DIAN_VARIANTS.items():
        labels = [dict(label) for label in MEME_LABELS]
        labels[0]["description"] = description

        hits = 0
        absorbed: dict[str, int] = {}
        for row in rows:
            got = engine.choose(row["text"], labels, CRITERION, args.perms)["winner"]
            if got == row["label"]:
                hits += 1
            else:
                absorbed[got] = absorbed.get(got, 0) + 1
        low, high = wilson(hits, len(rows))
        results.append((name, hits, len(rows), (low, high), absorbed))
        top = sorted(absorbed.items(), key=lambda kv: -kv[1])[:3]
        print(
            f"  {name:<14} {hits:>2}/{len(rows)} = {hits / len(rows) * 100:5.1f}%"
            f"  95% CI [{low * 100:4.1f}%, {high * 100:4.1f}%]"
            f"   错例去向 {top}"
        )

    print("\n=== 结论 ===")
    best = max(results, key=lambda item: item[1])
    base = results[0]
    print(f"  基线（shipped）{base[1]}/{base[2]}")
    print(f"  最好（{best[0]}）{best[1]}/{best[2]}")
    delta = best[1] - base[1]
    if delta <= 0:
        print("  没有候选优于基线 —— 这一轮改动不值得采用。")
    else:
        print(
            f"  好 {delta} 条。注意样本只有 {base[2]} 条，"
            f"{delta} 条在置信区间内可能是噪声，别当定论。"
        )


if __name__ == "__main__":
    main()
