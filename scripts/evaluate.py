"""八艺判定评测。

两套测试集：

  * ``data/eval_clean.jsonl`` —— **干净集**，`scripts/leak_check.py` 验证过
    与锚点描述无字面重合。**以这套的数字为准。**
  * ``data/eval_overlap.jsonl`` —— 对照集：页面示例的三个变体，
    外加一批**从干净集里揪出来的泄漏句**（id 前缀 ``leaked-``）。
    留着是为了让「泄漏长什么样」有据可查，**别拿它的数字当结论**。

跑之前先跑一遍 ``scripts/leak_check.py``，确认干净集还是干净的。

用法：
    .venv\\Scripts\\python.exe scripts\\evaluate.py
    .venv\\Scripts\\python.exe scripts\\evaluate.py --perms 3,5,7
    .venv\\Scripts\\python.exe scripts\\evaluate.py --data data\\eval_overlap.jsonl
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from jev_meme import DEFAULT_MODEL_DIR, DEFAULT_REVISION, LABEL_IDS, MemeJev  # noqa: E402

DATASETS = {
    "clean": PROJECT_ROOT / "data" / "eval_clean.jsonl",
    "overlap": PROJECT_ROOT / "data" / "eval_overlap.jsonl",
}


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def wilson(hits: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson 区间。

    样本小的时候必须报区间：几十条样本上「80.8%」的真实含义是
    「大约 68%~89%」—— 不报区间就等于假装几十条能定到小数点后一位。
    """
    if total == 0:
        return (0.0, 0.0)
    p = hits / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def write_result(payload: dict) -> None:
    """把头条数字记到 `data/eval_result.json`。

    为什么要有这个文件：网页和文档都要引用「干净集准确率」这一个数，
    手写就一定会过期（`web/index.html` 曾经写着 24 条 96%，而那时
    测试集早就换成 52 条了）。现在页面是**从这个文件读**的，
    所以只要用 `--write-result` 重跑一次评测，页面就跟着更新。
    """
    path = PROJECT_ROOT / "data" / "eval_result.json"
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n已写入 {path}（网页从这里读头条数字）")


def main() -> None:
    parser = argparse.ArgumentParser(description="八艺判定评测")
    parser.add_argument("--data", type=Path, default=None, help="指定测试集（默认两套都跑）")
    parser.add_argument("--perms", default="3,5,7", help="逗号分隔的排列数")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument(
        "--write-result",
        action="store_true",
        help="把干净集的头条数字写进 data/eval_result.json（网页和文档从这里读）",
    )
    parser.add_argument(
        "--result-perms",
        type=int,
        default=5,
        help="写进 eval_result.json 的是哪一档（默认 5 = 页面默认档）",
    )
    args = parser.parse_args()

    engine = MemeJev(model_dir=args.model_dir, revision=args.revision, device=args.device)
    engine.load()
    print(f"设备 {engine.metadata['device']} / {engine.metadata['dtype']}")
    print(f"词表 {''.join(LABEL_IDS)}\n")

    targets = (
        [("custom", args.data, load_rows(args.data))]
        if args.data
        else [(name, path, load_rows(path)) for name, path in DATASETS.items()]
    )

    summary: list[tuple[str, int, int, int, float, float, float]] = []

    for name, path, rows in targets:
        covered = {r["label"] for r in rows}
        print(f"===== [{name}] {path.name}：{len(rows)} 条，覆盖 {len(covered)} 个词 =====")
        if covered != set(LABEL_IDS):
            print(f"    注意：未覆盖全部词表 {' '.join(LABEL_IDS)}")
        if name == "overlap":
            print("    对照集：里面装着已知和锚点撞过车的句子，数字不代表泛化能力。")

        for perms in [int(p) for p in args.perms.split(",")]:
            hits = 0
            latencies: list[float] = []
            per_label: dict[str, list[int]] = defaultdict(lambda: [0, 0])
            misses: list[str] = []

            for row in rows:
                result = engine.decide(row["text"], permutations=perms)
                latencies.append(result["total_ms"])
                ok = result["winner"] == row["label"]
                hits += ok
                per_label[row["label"]][1] += 1
                per_label[row["label"]][0] += ok
                if not ok:
                    misses.append(f"{row['id']}:{row['label']}->{result['winner']}")

            latencies.sort()
            median = latencies[len(latencies) // 2]
            low, high = wilson(hits, len(rows))
            print(
                f"    {perms} 排列: {hits}/{len(rows)} = {hits / len(rows) * 100:3.1f}%"
                f"   95% CI [{low * 100:.1f}%, {high * 100:.1f}%]"
                f"   端到端中位 {median:5.0f} ms"
            )
            print("      分标签: " + "  ".join(f"{k}{v[0]}/{v[1]}" for k, v in sorted(per_label.items())))
            if misses:
                print(f"      错例({len(misses)}): " + " ".join(misses[:10]))
            summary.append((name, perms, hits, len(rows), median, low, high))
        print()

    print("===== 汇总 =====")
    for name, perms, hits, total, median, low, high in sorted(summary, key=lambda x: (x[0], x[1])):
        print(
            f"  [{name:<8}] {perms} 排列  {hits:>2}/{total} = {hits / total * 100:3.1f}%"
            f"   95% CI [{low * 100:.1f}%, {high * 100:.1f}%]"
            f"   中位 {median:5.0f} ms"
        )
    print()
    print("判断泛化能力只看 clean 那套 —— overlap 里有句子和锚点撞过车。")

    if args.write_result:
        # `--data` 指定单套时名字是 "custom"，默认两套都跑时干净集叫 "clean"。
        picked = [
            row
            for row in summary
            if row[0] in ("clean", "custom") and row[1] == args.result_perms
        ]
        if not picked:
            print(
                f"\n没有跑到 clean / {args.result_perms} 排列，"
                f"没写 eval_result.json（加上 --perms {args.result_perms} 再试）"
            )
            return
        _, perms, hits, total, median, low, high = picked[0]
        write_result(
            {
                "dataset": "data/eval_clean.jsonl",
                "permutations": perms,
                "total": total,
                "correct": hits,
                "accuracy": round(hits / total, 4),
                "ci95": [round(low, 4), round(high, 4)],
                "median_ms": round(median, 1),
                "note": "由 scripts/evaluate.py --write-result 生成；网页和文档从这里读头条数字",
            }
        )


if __name__ == "__main__":
    main()
