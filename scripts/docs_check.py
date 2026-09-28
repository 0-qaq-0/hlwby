"""文档与代码的一致性检查：README 里的**数字**和**路径**不许过期。

## 为什么需要它

这个项目被同一类问题坑过两次：

  * 页面上硬编码「干净测试集 24 条实测 96%」，测试集换成 52 条之后没人记得改，
    一个作废的数字在首页挂了很久（见 docs/EVAL.md 第六节）；
  * README 里同时写着「58 个单元测试」和「70 个单元测试」—— 两个都不对。

两次都是**同一个根因**：文档里手写的数字没有东西盯着。准确率已经有
`data/eval_result.json` 这个唯一出处了，这个脚本负责剩下那部分：

  * README 里写的头条准确率 / 样本量，必须等于 `data/eval_result.json`；
  * README 里写的单元测试数量，必须等于 `unittest` 实际收集到的用例数；
  * README 的「项目结构」里列的每个文件都得真实存在；
  * 反过来，仓库里的脚本 / 模块 / 文档也得在结构里出现（新增文件别忘登记）；
  * 归属表述不许退回「开源版 Jev」。

用法：
    .venv\\Scripts\\python.exe scripts\\docs_check.py
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

README = PROJECT_ROOT / "README.md"
EVAL_RESULT = PROJECT_ROOT / "data" / "eval_result.json"


def _enable_utf8() -> None:
    """把 stdout / stderr 切到 UTF-8。

    和 `biaochi/console.py` 里的同名函数是同一件事，**故意各写一份**：
    import 那个会连带拉起 `biaochi/__init__` -> engine -> torch，
    而这个检查脚本的价值就在于「别的东西坏了的时候它还能跑」。
    见 `biaochi/console.py` 开头对这件事的完整说明。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


_enable_utf8()

#: 这些路径在 README 里会出现，但**不一定**存在于当前工作区（不入库的东西）。
SKIP_PREFIXES = ("models/", ".venv/", "dist/", "data/profiles/", "data/eval_results/")

problems: list[str] = []
notes: list[str] = []


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


readme = read(README)


# ------------------------------------------------------------ 头条数字

print("头条数字:")
if not EVAL_RESULT.is_file():
    notes.append("还没有 data/eval_result.json，跳过数字检查（先跑 evaluate.py --write-result）")
    print("  结果文件不存在，跳过")
else:
    result = json.loads(EVAL_RESULT.read_text(encoding="utf-8"))
    total, accuracy = result["total"], result["accuracy"]

    # README 里的写法：「52 条实测 80.8%」
    hits = re.findall(r"(\d+)\s*条实测\s*\**\s*([\d.]+)\s*%", readme)
    if not hits:
        problems.append("README 里找不到「N 条实测 X%」这样的头条数字 —— 它应该写出来")
        print("  没找到「N 条实测 X%」")
    for sample_count, percent in hits:
        ok_total = int(sample_count) == total
        ok_acc = abs(float(percent) - round(accuracy * 100, 1)) < 0.05
        mark = "一致" if (ok_total and ok_acc) else "不一致 <-- 需要更新"
        print(f"  README 写 {sample_count} 条 / {percent}% ；结果文件 {total} 条 / {accuracy * 100:.1f}% —— {mark}")
        if not (ok_total and ok_acc):
            problems.append(
                f"README 的头条数字和 data/eval_result.json 不一致："
                f"README {sample_count} 条 {percent}% vs 文件 {total} 条 {accuracy * 100:.1f}%"
            )

    # 置信区间也得对得上。
    if result.get("ci95"):
        low, high = (round(x * 100, 1) for x in result["ci95"])
        printed = re.search(r"95%\s*CI\s*([\d.]+)%\s*~\s*([\d.]+)%", readme)
        if printed:
            same = abs(float(printed.group(1)) - low) < 0.05 and abs(float(printed.group(2)) - high) < 0.05
            print(f"  置信区间 README {printed.group(1)}~{printed.group(2)}% vs 文件 {low}~{high}% —— "
                  f"{'一致' if same else '不一致 <-- 需要更新'}")
            if not same:
                problems.append("README 的置信区间和结果文件不一致")
        else:
            notes.append("README 里没写置信区间（建议写，几十条样本必须报区间）")


# ------------------------------------------------------------ 单元测试数量

print("\n单元测试数量:")
declared = re.findall(r"(\d+)\s*个单元测试", readme)
if not declared:
    notes.append("README 里没有写单元测试数量（可选，但写了就得对）")
    print("  README 没写数量，跳过")
else:
    suite = unittest.TestLoader().discover(str(PROJECT_ROOT / "tests"), top_level_dir=str(PROJECT_ROOT))
    actual = suite.countTestCases()
    for number in declared:
        mark = "一致" if int(number) == actual else "不一致 <-- 需要更新"
        print(f"  README 写 {number} 个；实际收集到 {actual} 个 —— {mark}")
        if int(number) != actual:
            problems.append(f"README 写 {number} 个单元测试，实际 {actual} 个")


# ------------------------------------------------------------ 项目结构里的路径

print("\n项目结构:")


def structure_block(text: str) -> str:
    match = re.search(r"## 八、项目结构\s*\n+```\n(.*?)```", text, re.S)
    return match.group(1) if match else ""


block = structure_block(readme)
if not block:
    problems.append("README 里找不到「八、项目结构」的代码块（这个检查要靠它）")
    print("  找不到结构块")
else:
    checked = 0
    missing = []
    for raw_line in block.splitlines():
        body = raw_line.split("#", 1)[0]
        for token in re.split(r"[\s│├└─]+", body):
            token = token.strip()
            if not token or token in ("/", "标尺/", "|"):
                continue
            if token.startswith(SKIP_PREFIXES):
                continue
            # 同一行里写「一键启动.bat / start.sh」这种，按 / 切开逐个查。
            for piece in token.split("/"):
                piece = piece.strip()
                if not piece or piece == "标尺":
                    continue
                checked += 1
                if (PROJECT_ROOT / piece).exists():
                    continue
                # 结构块是缩进的树，子项只写了 basename —— 全树找一次。
                if any(PROJECT_ROOT.rglob(piece)):
                    continue
                missing.append(piece)
    print(f"  查了 {checked} 个路径名")
    if missing:
        for name in sorted(set(missing)):
            print(f"  结构里列了但找不到：{name} <-- 需要清理")
        problems.append(f"README 的项目结构里列了不存在的路径：{sorted(set(missing))}")
    else:
        print("  全部存在")

    # 反方向：仓库里有的，结构里得登记。
    undocumented = []
    for pattern, label in [
        ("scripts/*.py", "脚本"),
        ("scripts/*.ps1", "脚本"),
        ("biaochi/*.py", "模块"),
        ("docs/*.md", "文档"),
    ]:
        for path in sorted(PROJECT_ROOT.glob(pattern)):
            if path.name.startswith("__"):
                continue
            if path.name not in readme:
                undocumented.append(f"{path.relative_to(PROJECT_ROOT)}（{label}）")
    if undocumented:
        for name in undocumented:
            print(f"  存在但结构里没登记：{name}")
        problems.append(f"这些文件没写进 README 的项目结构：{undocumented}")
    else:
        print("  仓库里的脚本 / 模块 / 文档都登记了")


# ------------------------------------------------------------ 归属表述
#
# 注意这里判的是「**主张**」而不是「出现过」。README 里有一节专门在**反驳**
# 这个说法（标题就叫「关于『开源版 Jev』这个说法」），那是文档不是主张 ——
# 所以带引号、或者同一行里有「不是 / 并非」的，算反驳，放过。
# 页面检查（scripts/page_check.py）里没有这条豁免，因为页面上不该出现这个词。

REFUTE_MARKERS = ("不是", "并非", "而不是", "别写", "错的", "无隶属")


def attribution_hits(text: str) -> list[str]:
    hits = []
    for line in text.splitlines():
        for pattern in (r"开源版\s*Jev", r"Jev\s*模型开源版"):
            match = re.search(pattern, line)
            if not match:
                continue
            quoted = f"「{match.group(0)}」" in line or f"“{match.group(0)}”" in line
            refuting = quoted or any(marker in line for marker in REFUTE_MARKERS)
            if not refuting:
                hits.append(f"{match.group(0)!r}（{line.strip()[:40]}…）")
    return hits


print("\n归属表述:")
targets = [README, *sorted((PROJECT_ROOT / "docs").glob("*.md"))]
for path in targets:
    hits = attribution_hits(read(path))
    name = path.relative_to(PROJECT_ROOT)
    if hits:
        for hit in hits:
            print(f"  {name}: {hit} <-- 需要清理")
        problems.append(f"{name} 里把 SemIf 说成了 Jev 的开源版：{hits}")
    else:
        print(f"  {name}: 无（引用并反驳的那种不算）")

# ------------------------------------------------------------ 词表写对没有
#
# 这个项目的**产品事实**就八个字：典 孝 急 乐 蚌 批 赢 麻。
# 而仓库所在的目录名里还带着另外四个字（绷 润 摆 寄）—— 那是早期 10 字版本
# 留下的痕迹。于是很容易出现「文档里把词表写成 典孝急乐绷赢麻润」这种错
# （release 包的 README-启动.md 第一版就是这么写的，肉眼扫三遍都没看出来）。
#
# 所以把它变成检查：凡是连续出现的「词表字样」，要么正好是那八个字，
# 要么必须写在「早期 10 个字版本」这种明确的历史说明里。

WORD_SET = "典孝急乐蚌批赢麻"
LEGACY_WORDS = "绷润摆寄"
LEGACY_MARKERS = ("早期", "10 个", "十个", "历史")

print("\n词表字样:")
doc_files = [README, PROJECT_ROOT / "README-启动.md", *sorted((PROJECT_ROOT / "docs").glob("*.md"))]
for path in doc_files:
    text = read(path)
    name = path.relative_to(PROJECT_ROOT)
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        # 去掉分隔符之后再看，这样「典 / 孝 / 急」和「典孝急」是同一种情况。
        joined = re.sub(r"[\s/、|·,，]+", "", line)
        for hit in re.finditer(rf"[{WORD_SET}{LEGACY_WORDS}]{{4,}}", joined):
            word = hit.group(0)
            if not any(ch in LEGACY_WORDS for ch in word):
                continue
            if any(marker in line for marker in LEGACY_MARKERS):
                continue  # 明确在讲历史的那句，放过
            found.append(f"{name}:{number} {word!r}")
    if found:
        for item in found:
            print(f"  {item} <-- 词表写错了，应该是「{WORD_SET}」")
        problems.append(f"词表字样不对：{found}")
    else:
        print(f"  {name}: 无")

if "无隶属关系" not in readme:
    problems.append("README 缺少「无隶属关系」这句归属说明")
    print("  README 的「无隶属关系」：缺 <-- 需要清理")
else:
    print("  README 的「无隶属关系」：有")


# ------------------------------------------------------------ 结论

if notes:
    print("\n提示:")
    for note in notes:
        print("  - " + note)
if problems:
    print("\n问题:")
    for item in problems:
        print("  - " + item)
    sys.exit(1)
print("\n检查：全部通过")
sys.exit(0)
