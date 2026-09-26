"""八艺 —— 词汇表的一致性检查。

检查项：
  * 词表就是八个字，顺序固定
  * 词 id 不重复、描述里带锚点例句
  * 页面示例覆盖全部词、无重复
  * 描述长度别太失衡（只提示，不算失败）
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jev_meme.labels import CRITERION, EXAMPLES, LABEL_IDS, MEME_LABELS  # noqa: E402

EXPECTED = "典孝急乐蚌批赢麻"

#: 描述字数极差的**参考**上限。超了只提示，不算失败。
#:
#: 实测教训：为了把极差压到这条线以内而删锚点例句，「八艺」准确率从 96% 掉到 88%。
#: **锚点数量比长度均衡更重要** —— 长度失衡只是放大位置偏置，而排列平均已经在压它。
#: 所以这里当警告看，别为了达标去删例句。
LENGTH_SPREAD_SOFT_LIMIT = 70

problems: list[str] = []
warnings: list[str] = []

print(f"词表（{len(LABEL_IDS)} 个）：{' '.join(LABEL_IDS)}")
print(f"判定问法：{CRITERION}")
print()
print("锚点（进 prompt 的，直接决定准确率）：")
lengths = []
for label in MEME_LABELS:
    lengths.append(len(label["description"]))
    print(f"  {label['id']}  {label['description']}")
print()
print("页面示例（给人看的）：")
for example in EXAMPLES:
    print(f"  [{example['label']}] {example['text']}")
print()

if "".join(LABEL_IDS) != EXPECTED:
    problems.append(f"词表顺序不对：{''.join(LABEL_IDS)}")
if len(LABEL_IDS) != 8:
    problems.append(f"词表数量 {len(LABEL_IDS)} != 8")
if len(set(LABEL_IDS)) != len(LABEL_IDS):
    problems.append("词 id 有重复")
if {e["label"] for e in EXAMPLES} != set(LABEL_IDS):
    problems.append("页面示例没有覆盖全部八个词")
if len({e["text"] for e in EXAMPLES}) != len(EXAMPLES):
    problems.append("页面示例有重复")
for label in MEME_LABELS:
    if "例：" not in label["description"]:
        problems.append(f"{label['id']} 的描述里没有锚点例句")

spread = max(lengths) - min(lengths)
print(f"描述字数 {min(lengths)}~{max(lengths)}，极差 {spread}")
if spread > LENGTH_SPREAD_SOFT_LIMIT:
    warnings.append(
        f"描述长度极差 {spread} 偏大（>{LENGTH_SPREAD_SOFT_LIMIT}），"
        f"会略微放大位置偏置（但别为此删锚点例句）"
    )

if warnings:
    print("\n提示：")
    for warning in warnings:
        print("  - " + warning)
print("检查：", "全部通过" if not problems else "；".join(problems))
sys.exit(1 if problems else 0)
