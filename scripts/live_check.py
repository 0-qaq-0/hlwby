"""对着已经跑起来的服务，实测准确率和延迟（三个速度档）。

用法：
    .venv\\Scripts\\python.exe scripts\\live_check.py [base_url]
"""

import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jev_meme.labels import EXAMPLES  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8770"


def decide(text, permutations):
    request = urllib.request.Request(
        BASE + "/api/decide",
        data=json.dumps({"text": text, "permutations": permutations}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read())


def load(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


with urllib.request.urlopen(BASE + "/api/health") as response:
    health = json.loads(response.read())
print(
    f"服务 {BASE} · {health['model_name']} · {health['device']}/{health['dtype']} · "
    f"默认 {health['default_permutations']} 排列 · 词表 {' '.join(health['labels'])}\n"
)

sets = [
    ("页面示例（8 条，挑的典型样本）", EXAMPLES),
    ("干净测试集（`leak_check.py` 验证过与锚点不重合）", load(ROOT / "data" / "eval_clean.jsonl")),
]

for title, rows in sets:
    print(f"===== {title} =====")
    for perms in (3, 5, 7):
        hits = 0
        latencies = []
        for row in rows:
            result = decide(row["text"], perms)
            latencies.append(result["total_ms"])
            hits += result["winner"] == row["label"]
        latencies.sort()
        median = latencies[len(latencies) // 2]
        print(
            f"  {perms} 排列: {hits}/{len(rows)} = {hits / len(rows) * 100:3.0f}%   "
            f"端到端中位 {median:5.0f} ms   最大 {latencies[-1]:5.0f} ms"
        )
    print()

print("===== 逐条明细（5 排列，干净测试集）=====")
for row in load(ROOT / "data" / "eval_clean.jsonl"):
    result = decide(row["text"], 5)
    ok = result["winner"] == row["label"]
    top3 = " ".join(f"{i['id']}{i['probability'] * 100:3.0f}%" for i in result["ranking"][:3])
    print(f"  [{'OK  ' if ok else 'miss'}] 期望{row['label']} 判成{result['winner']}  {top3}")
