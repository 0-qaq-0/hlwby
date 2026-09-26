"""页面静态检查：关键元素是否齐全、JS 有没有残留引用。"""

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

required = ["text", "go", "bars", "big", "chips", "status", "stats", "conf", "hint"]
missing = [name for name in required if f'id="{name}"' not in html]
print("元素:", "全部就位" if not missing else f"缺失 {missing}")

for stale in ["modes", "data-mode", "MODE", "noul", "score"]:
    hit = stale in html
    print(f"  残留 {stale!r}: {'有 <-- 需要清理' if hit else '无'}")

sys.exit(1 if missing else 0)
