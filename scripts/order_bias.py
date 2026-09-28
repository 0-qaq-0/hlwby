"""诊断：选项顺序会不会影响判定结果？（槽位位置偏置）

Jev 的读出方式是「看模型下一个 token 是哪个字母」。如果模型对字母本身有偏好
（比如偏爱 B），那么把同一个词放在不同位置就会得到不同答案 —— 这不是语义判断，
是位置偏置。

做法：同一条文本，用不同的选项排列各判一次，看赢家稳不稳；
再测「多种排列取平均」能不能把准确率拉回来。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from biaochi import DEFAULT_MODEL_DIR, DEFAULT_REVISION, CRITERION, MEME_LABELS, Biaochi  # noqa: E402

DEFAULT_DATA = PROJECT_ROOT / "data" / "eval_clean.jsonl"


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def permutations(labels: list[dict], count: int, seed: int = 0) -> list[list[dict]]:
    """原始顺序 + 若干随机排列（含一个整体反转，保证覆盖首尾位置）。"""
    rng = random.Random(seed)
    orders = [list(labels), list(reversed(labels))]
    while len(orders) < count:
        candidate = list(labels)
        rng.shuffle(candidate)
        orders.append(candidate)
    return orders[:count]


def main() -> None:
    parser = argparse.ArgumentParser(description="选项顺序偏置诊断")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--perms", type=int, default=5, help="参与平均的排列数")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    args = parser.parse_args()

    rows = load_rows(args.data)
    engine = Biaochi(model_dir=args.model_dir, revision=args.revision, device=args.device)
    engine.load()
    print(f"设备 {engine.metadata['device']} | 数据 {args.data.name} | {len(rows)} 条\n")

    orders = permutations(MEME_LABELS, args.perms)

    # 1) 单词判定：每个排列各自的准确率
    per_order_hits = [0] * len(orders)
    # 2) 稳定性：原始顺序的赢家，在其它排列下还是不是同一个
    stable = 0
    # 3) 取平均
    avg_hits = 0

    misses: list[str] = []
    for row in rows:
        probs_by_label: dict[str, float] = defaultdict(float)
        winners = []
        for index, order in enumerate(orders):
            # **必须显式传 permutations=1。**
            # 这个脚本要量的是「只用这一种排列」时的准确率；
            # 不传的话 choose() 会按默认值再展开 5 种排列取平均，
            # 于是每一种「单排列」其实都是 5 排列的平均值 ——
            # 量出来的极差和稳定性全是假的（这个 bug 真实存在过，
            # 直到和 bias_probe.py 的数字对不上才被发现）。
            result = engine.choose(row["text"], order, CRITERION, permutations=1)
            per_order_hits[index] += result["winner"] == row["label"]
            winners.append(result["winner"])
            for item in result["ranking"]:
                probs_by_label[item["id"]] += item["probability"] / len(orders)
        stable += len(set(winners)) == 1
        averaged = max(probs_by_label, key=probs_by_label.get)
        avg_hits += averaged == row["label"]
        if averaged != row["label"]:
            misses.append(f"{row['id']}:{row['label']}->{averaged}")

    total = len(rows)
    print("=== 单一排列下的准确率（同一个模型，只换选项顺序）===")
    for index in range(len(orders)):
        tag = "原始顺序" if index == 0 else ("完全反转" if index == 1 else f"随机排列{index - 1}")
        print(f"  {tag:<10} {per_order_hits[index]}/{total} = {per_order_hits[index] / total * 100:3.0f}%")
    spread = max(per_order_hits) - min(per_order_hits)
    print(f"  -> 极差 {spread} 条 = {spread / total * 100:.0f} 个百分点（这一部分纯粹是位置噪声）")

    print(f"\n=== 稳定性 ===")
    print(f"  所有 {len(orders)} 种排列都给出同一个答案：{stable}/{total} = {stable / total * 100:.0f}%")
    print(f"  -> 剩下 {total - stable} 条的结果取决于选项怎么排")

    print(f"\n=== 多排列取平均 ===")
    print(f"  {avg_hits}/{total} = {avg_hits / total * 100:.0f}%")
    if misses:
        print("  错例: " + " ".join(misses[:10]))


if __name__ == "__main__":
    main()
