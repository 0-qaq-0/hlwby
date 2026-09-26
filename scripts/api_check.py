"""API 校验与错误路径测试（对着已经跑起来的服务打）。"""

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8770"


def post(payload):
    req = urllib.request.Request(
        BASE + "/api/decide",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def get(path):
    try:
        with urllib.request.urlopen(BASE + path) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


cases = [
    ("空文本", {"text": ""}),
    ("只有空格", {"text": "   "}),
    ("缺字段", {}),
    ("类型错", {"text": 123}),
    ("超长", {"text": "啊" * 20001}),
    ("旧profile参数", {"text": "测试", "profile": "classic"}),
    ("非法permutations", {"text": "测试", "permutations": 0}),
]
for name, payload in cases:
    code, body = post(payload)
    message = body.get("error", "") if isinstance(body, dict) else ""
    print(f"  {name:<18} -> HTTP {code}  {message[:44]}")

code, body = post({"text": "随便吧，爱咋咋地。" * 200})
print(
    f"  {'长文本':<18} -> HTTP {code}  winner={body.get('winner')}  "
    f"tokens={body.get('input_tokens')}  {body.get('permutations')}排列  "
    f"fwd={body.get('forward_ms')}ms"
)

for path in ["/nope", "/api/nope", "/../requirements.txt"]:
    code, _ = get(path)
    print(f"  GET {path:<22} -> HTTP {code}")

code, body = get("/api/labels")
data = json.loads(body)
print(f"  GET /api/labels      -> HTTP {code}")
print(f"      词表 {len(data['labels'])} 个：{' '.join(l['id'] for l in data['labels'])}")
print(f"      示例 {len(data['examples'])} 条")
print(f"      问法 {data['criterion'][:34]}…")

code, body = get("/api/health")
health = json.loads(body)
print(
    f"  GET /api/health      -> HTTP {code}  模型={health['model_name']}  "
    f"默认{health['default_permutations']}排列"
)

# 每个词的页面示例判一遍
hits = 0
for example in data["examples"]:
    code, body = post({"text": example["text"]})
    ok = body["winner"] == example["label"]
    hits += ok
    print(
        f"  示例 · 期望{example['label']} 判成{body['winner']}"
        f"（{body['confidence'] * 100:.0f}%）{'OK' if ok else '<-- miss'}"
    )
print(f"  -> 页面示例 {hits}/{len(data['examples'])}")
