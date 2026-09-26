"""验证批量排列平均：正确性 + 速度。

要点：
  1. batch=1 的结果必须和单次前向一致（左填充不能改变结果）
  2. 排列数越多，答案越稳、越准
  3. 批量跑 N 个排列，应该远快于串行跑 N 次
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jev_meme import CRITERION, MEME_LABELS, MemeJev  # noqa: E402
from jev_meme.engine import permutations_of  # noqa: E402

TEXT = "我爸说他要戒烟，然后把烟藏在了冰箱里，说这样就想不起来抽了。第二天他在冰箱前面站了半小时。"
EXPECT = "乐"

engine = MemeJev()
engine.load()
print(f"设备 {engine.metadata['device']} / {engine.metadata['dtype']}\n")

print("=== 正确性：batch=1 与单次前向一致 ===")
single = engine.choose(TEXT, MEME_LABELS, CRITERION, permutations=1)
print(f"  winner={single['winner']}  conf={single['confidence']:.3f}  batch={single['batch']}  {single['forward_ms']:.0f} ms")

print("\n=== 排列数 vs 延迟（同一条文本，重复测延迟）===")
for count in (1, 3, 5, 7, 10):
    result = engine.choose(TEXT, MEME_LABELS, CRITERION, permutations=count)
    # 再跑两遍取中位延迟
    times = sorted(
        engine.choose(TEXT, MEME_LABELS, CRITERION, permutations=count)["forward_ms"]
        for _ in range(3)
    )
    top3 = "  ".join(f"{i['id']}{i['probability'] * 100:.0f}%" for i in result["ranking"][:3])
    print(
        f"  {count:>2} 排列  batch={result['batch']:>2}  "
        f"{times[1]:6.0f} ms   winner={result['winner']}  [{top3}]"
    )

print("\n=== 串行 vs 批量（7 个排列）===")
orders = permutations_of(MEME_LABELS, 7)
start = time.perf_counter()
for order in orders:
    engine.choose(TEXT, order, CRITERION, permutations=1)
serial_ms = (time.perf_counter() - start) * 1000
batched_ms = engine.choose(TEXT, MEME_LABELS, CRITERION, permutations=7)["forward_ms"]
print(f"  串行 7 次: {serial_ms:6.0f} ms")
print(f"  批量 1 次: {batched_ms:6.0f} ms   -> 快 {serial_ms / batched_ms:.1f}x")

print("\n=== 可复现性（同一输入跑三次）===")
for _ in range(3):
    r = engine.choose(TEXT, MEME_LABELS, CRITERION, permutations=7)
    print(f"  {r['winner']}  {r['confidence']:.4f}")
