"""对着**已经跑起来的服务**实测：页面示例、干净测试集、三个速度档。

和 `scripts/evaluate.py` 的区别：那个直接调引擎（自己加载模型），这个走 HTTP ——
测的是「用户实际打开页面时会发生什么」，所以能顺带验证 API 那一层。

从 v4 起判断类型可自定义，所以这里也认所有类型：
每一套类型都拿**它自己的页面示例**跑一遍（示例挑的是该类型的典型样本，
一个都判不对说明锚点写坏了）。内置「八艺」额外跑干净测试集和三个速度档。

用法：
    .venv\\Scripts\\python.exe scripts\\live_check.py
    .venv\\Scripts\\python.exe scripts\\live_check.py http://127.0.0.1:8770
    .venv\\Scripts\\python\\python.exe scripts\\live_check.py --only support-router
    .venv\\Scripts\\python.exe scripts\\live_check.py --no-dataset   # 只跑示例，很快
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tiaoyige.profiles import DEFAULT_PROFILE_ID  # noqa: E402


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read())


def post(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read())


def load_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="对着跑起来的服务实测")
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:8770", help="服务地址")
    parser.add_argument("--only", default=None, help="只测某一套判断类型")
    parser.add_argument("--perms", type=int, default=5, help="页面示例用几个排列")
    parser.add_argument("--no-dataset", action="store_true", help="跳过干净测试集（省时间）")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    try:
        health = get(base + "/api/health")
    except (urllib.error.URLError, OSError) as error:
        print(f"连不上 {base}：{error}")
        print("先把服务起起来：.venv\\Scripts\\python.exe -m tiaoyige.server")
        sys.exit(2)

    print(
        f"服务 {base} · 帮你挑一个 v{health.get('version', '?')} · {health['model_name']} · "
        f"{health['device']}/{health['dtype']} · 默认 {health['default_permutations']} 排列"
    )
    print(f"判断类型 {len(health['profiles'])} 套：{'、'.join(health['profiles'])}\n")

    profiles = [p for p in get(base + "/api/profiles")["profiles"] if not args.only or p["id"] == args.only]
    if not profiles:
        print(f"没有这个判断类型：{args.only}")
        sys.exit(2)

    # ---------------------------------------------------------- 页面示例
    #
    # 示例是「该类型的典型样本」——判不对说明锚点写坏了。注意它**不是**准确率：
    # 示例只有几条，而且是人挑的。真正的数字只能来自干净测试集。
    total_hits = total_rows = 0
    for summary in profiles:
        detail = get(f"{base}/api/profiles/{summary['id']}")
        profile = detail["profile"]
        examples = profile["examples"]
        print(f"===== [{profile['id']}] {profile['name']} 的页面示例（{len(examples)} 条）=====")
        if not examples:
            print("  （这套类型没配页面示例）\n")
            continue
        hits = 0
        for example in examples:
            result = post(base + "/api/decide", {
                "text": example["text"], "permutations": args.perms, "profile": profile["id"],
            })
            ok = result["winner"] == example["label"]
            hits += ok
            mark = "OK  " if ok else "miss"
            top3 = " ".join(f"{r['id']}{r['probability'] * 100:3.0f}%" for r in result["ranking"][:3])
            print(f"  [{mark}] 期望{example['label']} 判成{result['winner']}  {top3}")
        print(f"  -> {hits}/{len(examples)}\n")
        total_hits += hits
        total_rows += len(examples)

    if total_rows:
        print(f"页面示例合计：{total_hits}/{total_rows}\n")

    if args.no_dataset:
        return

    # ------------------------------------------------- 干净测试集（只测「八艺」）
    #
    # 测试集的 label 是「八艺」的八个字，所以只能拿它量「八艺」——
    # 自定义类型要自己准备一份同口径的测试集（见 docs/CUSTOMIZE.md）。
    bayi = next((p for p in profiles if p["id"] == DEFAULT_PROFILE_ID), None)
    rows = load_rows(ROOT / "data" / "eval_clean.jsonl")
    if bayi is None or not rows:
        print("跳过干净测试集（要么没测八艺，要么 data/eval_clean.jsonl 不在）")
        return

    print("===== 干净测试集（leak_check.py 验证过与锚点不重合）=====")
    for perms in (3, 5, 7):
        hits = 0
        latencies = []
        for row in rows:
            result = post(base + "/api/decide", {
                "text": row["text"], "permutations": perms, "profile": DEFAULT_PROFILE_ID,
            })
            latencies.append(result["total_ms"])
            hits += result["winner"] == row["label"]
        latencies.sort()
        median = latencies[len(latencies) // 2]
        print(
            f"  {perms} 排列: {hits}/{len(rows)} = {hits / len(rows) * 100:3.1f}%   "
            f"端到端中位 {median:5.0f} ms   最大 {latencies[-1]:5.0f} ms"
        )
    print()


if __name__ == "__main__":
    main()
