"""页面静态检查：关键元素是否齐全、JS 有没有残留引用、**头条数字有没有硬编码**。

最后一条是新增的，也是这个脚本现在最有价值的一条 —— 见下面 `FORBIDDEN` 的注释。
"""

import pathlib
import re
import sys

root = pathlib.Path(__file__).resolve().parent.parent
html = (root / "web" / "index.html").read_text(encoding="utf-8")

scripts = re.findall(r"<script>(.*?)</script>", html, re.S)
out = root / ".cache" / "page.js"
out.parent.mkdir(exist_ok=True)
out.write_text("\n".join(scripts), encoding="utf-8")
print(f"script 块 {len(scripts)} 个，JS {sum(len(s) for s in scripts)} 字符")

problems: list[str] = []

#: 页面里必须有这些元素。
required = [
    "text",
    "go",
    "bars",
    "big",
    "chips",
    "status",
    "stats",
    "conf",
    "hint",
    # 头条数字的两个占位符：数值由 /api/eval 填，不在 HTML 里写死。
    "eval-accuracy",
    "eval-detail",
]
missing = [name for name in required if f'id="{name}"' not in html]
print("元素:", "全部就位" if not missing else f"缺失 {missing}")
if missing:
    problems.append(f"缺少元素 {missing}")

#: 旧版本留下的、不该再出现的东西。
for stale in ["modes", "data-mode", "MODE", "noul", "score"]:
    hit = stale in html
    print(f"  残留 {stale!r}: {'有 <-- 需要清理' if hit else '无'}")
    if hit:
        problems.append(f"页面里还有旧版本的残留：{stale}")

# ---------------------------------------------------------------- 硬编码检查
#
# 页面曾经写死「干净测试集 24 条实测 96%」。后来测试集因为修数据泄漏
# 从 24 条换成 52 条、真实水平是 80.8%，而页面上那个 96% 一直没人改 ——
# 一个**已经作废的数字**就这么在首页挂着了。
#
# 现在数字由 `/api/eval` 提供（源头是 `data/eval_result.json`，
# 由 `scripts/evaluate.py --write-result` 生成），HTML 里只留占位符。
# 这条检查就是防止有人再把数字写回去。
#
# 注意：检查前先把**注释**去掉。注释里会引用旧数字来说明「为什么要改」，
# 那是文档，不是主张 —— 不区分的话这个检查会被自己的说明文字绊倒。
def strip_comments(source: str) -> str:
    source = re.sub(r"<!--.*?-->", "", source, flags=re.S)
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("//")
    )


visible = strip_comments(html)

HARDCODED = [
    (r"\d+\s*条实测", "别在页面里写死样本量 —— 走 /api/eval"),
    (r"实测\s*<b[^>]*>\s*\d", "别在页面里写死准确率 —— 走 /api/eval"),
]

print("\n硬编码检查:")
for pattern, why in HARDCODED:
    hit = re.search(pattern, visible)
    if hit:
        print(f"  命中 /{pattern}/ -> {hit.group(0)!r}  {why}")
        problems.append(f"页面硬编码了头条数字：{hit.group(0)!r} —— {why}")
    else:
        print(f"  /{pattern}/ 无")

#: 归属表述也不能退回去。
for bad, why in [
    (r"开源版\s*Jev", "SemIf 是独立项目，不是 Jev 的开源版"),
    (r"Jev\s*模型开源版", "同上"),
]:
    hit = re.search(bad, visible)
    if hit:
        print(f"  归属说法 /{bad}/ -> {hit.group(0)!r}  {why}")
        problems.append(f"页面归属表述错误：{hit.group(0)!r} —— {why}")
    else:
        print(f"  归属说法 /{bad}/ 无")

if problems:
    print("\n问题:")
    for item in problems:
        print("  - " + item)
    sys.exit(1)
print("\n检查：全部通过")
sys.exit(0)
