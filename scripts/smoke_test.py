"""跑一遍八个示例，看看模型判得准不准、有多快。

用法：
    .venv\\Scripts\\python.exe scripts\\smoke_test.py
    .venv\\Scripts\\python.exe scripts\\smoke_test.py --text "随便吧，爱咋咋地。"
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from jev_meme import DEFAULT_MODEL_DIR, DEFAULT_REVISION, EXAMPLES, MemeJev  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="八艺判定冒烟测试")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--text", default=None, help="只判这一条，而不是跑全部示例")
    parser.add_argument("--perms", type=int, default=None, help="选项排列数（默认用引擎默认值）")
    args = parser.parse_args()

    engine = MemeJev(model_dir=args.model_dir, revision=args.revision, device=args.device)
    t0 = time.perf_counter()
    engine.load()
    print(
        f"模型加载 {time.perf_counter() - t0:.1f}s -> "
        f"{engine.metadata['device']} / {engine.metadata['dtype']}\n"
    )

    cases = [{"label": "自定义", "text": args.text}] if args.text else EXAMPLES

    hits = 0
    latencies: list[float] = []
    for case in cases:
        result = (
            engine.decide(case["text"])
            if args.perms is None
            else engine.decide(case["text"], permutations=args.perms)
        )
        latencies.append(result["forward_ms"])
        ok = result["winner"] == case["label"]
        hits += ok
        top3 = "  ".join(
            f"{item['id']} {item['probability'] * 100:5.1f}%" for item in result["ranking"][:3]
        )
        print(
            f"  [{'OK  ' if ok else 'miss'}] 期望 {case['label']} | 判成 {result['winner']} "
            f"({result['confidence'] * 100:.1f}%) | {result['forward_ms']:6.1f} ms | {top3}"
        )

    if not args.text:
        print(f"  -> 命中 {hits}/{len(cases)}")
    latencies.sort()
    median = latencies[len(latencies) // 2]
    print(f"  -> 推理延迟 中位 {median:.1f} ms / 最大 {latencies[-1]:.1f} ms")


if __name__ == "__main__":
    main()
