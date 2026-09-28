"""页面静态检查：文件齐不齐、JS 引用的元素在不在、**头条数字有没有硬编码**。

最后一条是这个脚本最有价值的一条 —— 见下面 `HARDCODED` 的注释。

从 v4 起页面拆成了多文件（`web/index.html` + `web/style.css` + `web/js/**`），
所以检查也跟着变了：以前只读一个 HTML，现在要
  * 确认每个模块文件都在；
  * 把 JS 里 `$("x")` / `getElementById("x")` 引用的 id 和 HTML 里 `id="x"` 对一遍
    —— 少一个 id 就是运行时的 `null` 崩溃，静态检查能提前抓到；
  * 数字检查覆盖整个 `web/`，不只是 HTML。
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

problems: list[str] = []


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------- 文件齐全

REQUIRED_FILES = [
    "index.html",
    "style.css",
    "js/main.js",
    "js/api.js",
    "js/util.js",
    "js/state.js",
    "js/tabs/judge.js",
    "js/tabs/editor.js",
    "js/tabs/eval.js",
    "js/tabs/settings.js",
]

print("文件:")
for name in REQUIRED_FILES:
    exists = (WEB / name).is_file()
    print(f"  {'有  ' if exists else '缺失'} web/{name}")
    if not exists:
        problems.append(f"缺少 web/{name}")

html = read(WEB / "index.html")
modules = {path: read(path) for path in sorted((WEB / "js").rglob("*.js"))}
all_js = "\n".join(modules.values())

# ------------------------------------------------------------ 入口引用

print("\n入口:")
if '<script type="module" src="/js/main.js">' not in html:
    problems.append("index.html 没有以 module 方式加载 /js/main.js")
    print("  main.js 入口：缺 <-- 需要清理")
else:
    print("  main.js 入口：有")
if 'href="/style.css"' not in html:
    problems.append("index.html 没有引用 /style.css")
    print("  style.css 引用：缺 <-- 需要清理")
else:
    print("  style.css 引用：有")

# 模块之间的相对 import 必须指向真实文件。
for path, source in modules.items():
    for target in re.findall(r'from\s+"(\.[^"]+)"', source):
        resolved = (path.parent / target).resolve()
        if not resolved.is_file():
            problems.append(f"{path.relative_to(ROOT)} 里 import 的 {target} 不存在")
            print(f"  断链 import: {path.name} -> {target}")

# ------------------------------------------------- JS 引用的 id 都在 HTML 里

print("\n元素 id:")
html_ids = set(re.findall(r'id="([^"]+)"', html))
js_ids: set[str] = set()
for source in modules.values():
    js_ids |= set(re.findall(r'\$\("([^"]+)"\)', source))
    js_ids |= set(re.findall(r'getElementById\("([^"]+)"\)', source))

missing_ids = sorted(js_ids - html_ids)
print(f"  HTML 里 {len(html_ids)} 个 id，JS 引用 {len(js_ids)} 个")
if missing_ids:
    for name in missing_ids:
        print(f"  JS 引用了不存在的 id: {name} <-- 运行时会 null")
    problems.append(f"JS 引用了 HTML 里没有的 id：{missing_ids}")
else:
    print("  JS 引用的 id 全部存在")

# 头条数字的两个占位符：数值由 /api/eval 填，不在 HTML 里写死。
for name in ("eval-accuracy", "eval-detail"):
    if f'id="{name}"' not in html:
        problems.append(f"缺少头条数字占位符 id=\"{name}\"")
        print(f"  占位符 {name}: 缺 <-- 需要清理")
    else:
        print(f"  占位符 {name}: 有")

if "/api/eval" not in all_js:
    problems.append("页面没有调用 /api/eval —— 头条数字会失去唯一出处")
    print("  /api/eval 调用：缺 <-- 需要清理")
else:
    print("  /api/eval 调用：有")

# ---------------------------------------------------------------- 硬编码检查
#
# 页面曾经写死「干净测试集 24 条实测 96%」。后来测试集因为修数据泄漏
# 从 24 条换成 52 条、真实水平是另一个数，而页面上那个 96% 一直没人改 ——
# 一个**已经作废的数字**就这么在首页挂着了。
#
# 现在数字由 `/api/eval` 提供（源头是 `data/eval_result.json`，
# 由 `scripts/evaluate.py --write-result` 生成），HTML/JS 里只留占位符。
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


HARDCODED = [
    (r"\d+\s*条实测", "别在页面里写死样本量 —— 走 /api/eval"),
    (r"实测\s*<b[^>]*>\s*\d", "别在页面里写死准确率 —— 走 /api/eval"),
    (r"(准确率|accuracy)[^\"'\n]{0,24}\d+(?:\.\d+)?\s*%", "别在页面里写死准确率 —— 走 /api/eval"),
    (r"\d+(?:\.\d+)?\s*%[^\"'\n]{0,10}(准确率|accuracy)", "同上"),
]

print("\n硬编码检查:")
for name in ["index.html", "style.css", *[str(p.relative_to(WEB)) for p in modules]]:
    path = WEB / name
    visible = strip_comments(read(path))
    for pattern, why in HARDCODED:
        hit = re.search(pattern, visible)
        if hit:
            print(f"  web/{name} 命中 /{pattern}/ -> {hit.group(0)!r}  {why}")
            problems.append(f"web/{name} 硬编码了头条数字：{hit.group(0)!r} —— {why}")
print("  （没命中就是通过）" if not any(
    re.search(pattern, strip_comments(read(WEB / name)))
    for name in ["index.html", "style.css", *[str(p.relative_to(WEB)) for p in modules]]
    for pattern, _ in HARDCODED
) else "  见上")

# ---------------------------------------------------------------- 归属表述

print("\n归属表述:")
for bad, why in [
    (r"开源版\s*Jev", "SemIf 是独立项目，不是 Jev 的开源版"),
    (r"Jev\s*模型开源版", "同上"),
]:
    hits = [name for name in ["index.html", *[str(p.relative_to(WEB)) for p in modules]]
            if re.search(bad, read(WEB / name))]
    if hits:
        print(f"  /{bad}/ 命中 {hits}  {why}")
        problems.append(f"页面归属表述错误（{hits}）：{why}")
    else:
        print(f"  /{bad}/ 无")

for needed in ("独立", "无隶属关系"):
    if needed not in html:
        problems.append(f"页面缺少归属说明「{needed}」")
        print(f"  「{needed}」：缺 <-- 需要清理")
    else:
        print(f"  「{needed}」：有")

# ---------------------------------------------------------------- 结论

if problems:
    print("\n问题:")
    for item in problems:
        print("  - " + item)
    sys.exit(1)
print("\n检查：全部通过")
sys.exit(0)
