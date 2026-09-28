"""数据泄漏检查：测试集 / 页面示例 与 锚点描述 的字符 n-gram 重合度。

## 为什么需要这个脚本

`docs/EVAL.md` 第 3 节记了本项目最大的一次翻车：先写测试集、再写锚点，
无意识复用了同一批句子，于是测出 24/24 = 100% 的假数字，
换成内容真正不重合的干净集之后同一个模型掉到 50%。

那次之后建了 `data/eval_clean.jsonl`，靠**人工**保证它和锚点不重合。
但锚点后来又改过几版（现在是 `meme-direct-zh-v4`），
**没有任何机制保证它一直干净** —— 实测确实又漏了：
`ying-1/2/3`、`pi-1/3`、`beng-1`、`ma-3`、`ji-1/2`、`le-1` 这些句子
几乎逐字出现在锚点例句里。这种泄漏会把准确率抬高到没有意义的水平。

所以这里把它变成一个**可执行的检查**，而不是一句承诺。

## 做法

两边都只保留中英文数字（去掉标点、空白），再比字符 n-gram 的集合重合率。
分母取较短一侧的 n-gram 数量 —— 否则长描述天然占便宜，
一句 20 字的测试句对上一段 120 字的锚点，重合率会被稀释成 0。

阈值（默认 8-gram）：

    >= 0.30   LEAK —— 这句话基本能在锚点里逐字找到，必须挪出干净集
    >= 0.15   warn —— 可疑，人工看一眼

用法：
    .venv\\Scripts\\python.exe scripts\\leak_check.py
    .venv\\Scripts\\python.exe scripts\\leak_check.py --n 6 --strict
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from jev_meme.labels import EXAMPLES, MEME_LABELS  # noqa: E402

DATA_DIR = PROJECT_ROOT / "data"

#: 只留中英文数字，标点空白全部丢掉 —— 泄漏往往是「同一句话改了标点」。
_KEEP = re.compile(r"[^\u4e00-\u9fffA-Za-z0-9]")

LEAK_THRESHOLD = 0.30
WARN_THRESHOLD = 0.15


#: 比这个还短的窗口就没有区分度了（「嗯嗯受教了」这种 5 字句会整个命中）。
MIN_WINDOW = 5


def normalize(text: str) -> str:
    return _KEEP.sub("", text)


def overlap(query: str, haystack: str, n: int) -> float:
    """``query`` 里有多大比例的字面片段能在 ``haystack`` 里逐字找到。

    方向是**单向**的：我们关心的是「这句测试句是不是抄了锚点」，
    而不是「锚点是不是抄了测试句」。所以窗口大小取
    ``min(n, len(query))`` —— 否则像「嗯嗯，受教了。」这种 5 字短句
    永远凑不出 8-gram，会从检查里溜过去（这是本脚本第一版的 bug，
    短句正是「麻」这个词的全部形态，漏掉等于没查）。
    """
    q = normalize(query)
    if not q:
        return 0.0
    width = min(n, len(q))
    if width < MIN_WINDOW:
        # 句子太短，任何片段都不足以说明问题 —— 宁可放过，不要误报。
        return 0.0
    grams = {q[i : i + width] for i in range(len(q) - width + 1)}
    hay = normalize(haystack)
    hits = sum(1 for gram in grams if gram in hay)
    return hits / len(grams)


def worst_against(text: str, n: int) -> tuple[float, str]:
    """这句话和哪个锚点最像，像到什么程度。"""
    best, who = 0.0, "—"
    for label in MEME_LABELS:
        score = overlap(text, label["description"], n)
        if score > best:
            best, who = score, label["id"]
    return best, who


def verdict(score: float) -> str:
    if score >= LEAK_THRESHOLD:
        return "LEAK"
    if score >= WARN_THRESHOLD:
        return "warn"
    return "ok"


def load_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="测试集 / 页面示例 与锚点的泄漏检查")
    parser.add_argument("--n", type=int, default=8, help="字符 n-gram 的 n（默认 8）")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="把 warn 也算失败（默认只有 LEAK 才算失败）",
    )
    args = parser.parse_args()

    print(f"锚点版本：{len(MEME_LABELS)} 段描述，n-gram n={args.n}")
    print(f"阈值：>= {LEAK_THRESHOLD} 判泄漏，>= {WARN_THRESHOLD} 判可疑\n")

    leaks = 0
    warns = 0
    #: 只有这两处泄漏才算失败 —— `eval_overlap.jsonl` 存在的意义就是收留泄漏样本。
    hard_failures = 0

    # ---------------------------------------------------------- 测试集
    for name in ("eval_clean", "eval_overlap"):
        path = DATA_DIR / f"{name}.jsonl"
        rows = load_rows(path)
        if not rows:
            print(f"===== [{name}] 文件不存在或为空，跳过 =====")
            continue
        # 对照集本来就装着撞过车的句子，它再漏是正常的，不算失败。
        advisory = name == "eval_overlap"
        head = "（对照集，泄漏属预期，不计入失败）" if advisory else ""
        print(f"===== [{name}] {path.name}：{len(rows)} 条 {head}=====")
        bad = []
        for row in rows:
            score, who = worst_against(row["text"], args.n)
            mark = verdict(score)
            if mark == "LEAK":
                leaks += 1
                bad.append(row)
                if not advisory:
                    hard_failures += 1
                print(f"  LEAK  {row['id']:<16} 标准答案={row['label']}  最像锚点「{who}」 {score:.2f}")
                print(f"        {row['text']}")
            elif mark == "warn":
                warns += 1
                print(f"  warn  {row['id']:<16} 标准答案={row['label']}  最像锚点「{who}」 {score:.2f}")
        if not bad:
            print("  （无泄漏）")
        print()

    # ------------------------------------------------------ 页面示例
    print(f"===== [页面示例] jev_meme/labels.py EXAMPLES：{len(EXAMPLES)} 条 =====")
    example_bad = 0
    for example in EXAMPLES:
        score, who = worst_against(example["text"], args.n)
        mark = verdict(score)
        if mark == "LEAK":
            leaks += 1
            hard_failures += 1
            example_bad += 1
            print(f"  LEAK  [{example['label']}] 最像锚点「{who}」 {score:.2f}")
            print(f"        {example['text']}")
        elif mark == "warn":
            warns += 1
            print(f"  warn  [{example['label']}] 最像锚点「{who}」 {score:.2f}")
    if not example_bad:
        print("  （无泄漏）")
    print()

    # ---------------------------------------------------------- 结论
    print("===== 结论 =====")
    if hard_failures:
        print(f"  干净集 / 页面示例有 {hard_failures} 条泄漏 —— 必须挪走，否则准确率是虚高的。")
    else:
        print("  干净集和页面示例都没有泄漏。")
    if leaks > hard_failures:
        print(f"  另有 {leaks - hard_failures} 条在对照集里，属预期（那套就是用来装泄漏样本的）。")
    if warns:
        print(f"  {warns} 条可疑，人工看一眼。")
    print(
        "\n注意：这个检查只能挡住**字面**泄漏。语义上「换了个说法但意思一样」"
        "\n的泄漏它看不出来，那部分只能靠写锚点时不去看测试集。"
    )

    failed = hard_failures > 0 or (args.strict and warns > 0)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
