"""锚点写法与问法对比实验。

用途：以后想改锚点时，先用这个脚本在**干净测试集**上验证，别直接改发布版。

    .venv\\Scripts\\python.exe scripts\\experiment.py
    .venv\\Scripts\\python.exe scripts\\experiment.py --variants shipped,short
    .venv\\Scripts\\python.exe scripts\\experiment.py --criterion abstract

历史结论（详见 docs/EVAL.md）：
  * 「多锚点例句」远胜「长抽象定义」。
  * 加「区别：这不是 X」式元说明会**变差** —— 描述里提到别的词名会把概率漏给那些词。
  * 锚点要描述「文本长什么样」，不是「说话人在干什么」。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tiaoyige import DEFAULT_MODEL_DIR, DEFAULT_REVISION, MEME_LABELS, Tiaoyige  # noqa: E402

DEFAULT_DATA = PROJECT_ROOT / "data" / "eval_clean.jsonl"

#: 各词的极简描述（只留一句最有辨识度的话）。
SHORT: dict[str, str] = {
    "典": "对方在讲道理、分析原因、下判断，一段不长不短的普通论述。",
    "孝": "对方在夸某个公司、品牌、平台、老板或名人，替他说话、替他辩解。",
    "急": "对方在逐条辩论、分点回击，读起来像在跟人抬杠。",
    "乐": "对方在用大词、术语、抽象概念绕来绕去，故弄玄虚，看完不知道在说什么。",
    "蚌": "对方把问题踢回给你，逼你表态、要你拿方案。",
    "批": "对方一刀切地批判、声讨、下判决，用「都」「该」「就是」把一整类人打死。",
    "赢": "对方说的是一句格言腔的金句：对仗、押韵，去掉修辞没多少信息量。",
    "麻": "只有一句敷衍的附和或认输，非常短，没有实质内容。",
}

#: 只给关键词，最省 token。
KEYWORD: dict[str, str] = {
    "典": "陈述观点、分析原因、下判断",
    "孝": "吹捧品牌、替强者说话、护主",
    "急": "分点辩论、逐条回击、抬杠",
    "乐": "术语堆砌、故弄玄虚、看不懂",
    "蚌": "反问、逼你表态、要方案",
    "批": "一刀切批判、扣帽子、下判决",
    "赢": "格言腔、对仗、金句",
    "麻": "敷衍附和、认输、极短",
}

#: 描述「说话人在干什么」而不是「文本长什么样」—— 这是失败过的写法，留作对照。
RELATIONAL: dict[str, str] = {
    "典": "当对方陈述观点时，不管说得对不对，就回「典」。",
    "孝": "当对方支持自己不支持的人或事时，回「孝」。",
    "急": "当对方辩论，或是开始细致解说时，回「急」。",
    "乐": "当自己难以理解对方表达的观点时，回「乐」。",
    "蚌": "当对方要求你表达不存在的观点时，回「蚌」。",
    "批": "当对方产生足以称为立场的观点时，回「批」。",
    "赢": "当自己说出自认为一针见血的话时，回「赢」。",
    "麻": "当无法对对方言论进行有效反驳时，回「麻」。",
}

VARIANTS: dict[str, tuple[dict[str, str], str]] = {
    "shipped": ({l["id"]: l["description"] for l in MEME_LABELS}, "当前发布版（多锚点例句）"),
    "short": (SHORT, "极简一句话"),
    "keyword": (KEYWORD, "只给关键词"),
    "relational": (RELATIONAL, "照「八艺」定义字面写（已知会失败，作对照）"),
}

#: 同一套描述，换不同的问法。
CRITERIA: dict[str, str] = {
    "bayi": "下面这句网上的发言，最符合「八艺」里的哪一个？请选出最贴切的那一个。",
    "abstract": "下面这段网络发言，最主要体现的是哪一种心态、姿态或场面？请选出最贴切的那一个。",
    "danmu": "如果只能用一个字回复下面这段话（就像发一条弹幕），你会发哪个字？请选出最贴切的那一个。",
}


def build_labels(descriptions: dict[str, str]) -> list[dict[str, str]]:
    """按内置顺序拼出标签列表，保留 id / pinyin / hint / accent。"""
    meta = {label["id"]: label for label in MEME_LABELS}
    return [{**meta[label_id], "description": text} for label_id, text in descriptions.items()]


def load_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="锚点写法 / 问法对比")
    parser.add_argument("--variants", default="shipped,short,keyword,relational")
    parser.add_argument("--criteria", default="bayi")
    parser.add_argument("--perms", type=int, default=5)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    args = parser.parse_args()

    rows = load_rows(args.data)
    engine = Tiaoyige(model_dir=args.model_dir, revision=args.revision, device=args.device)
    engine.load()
    print(f"设备 {engine.metadata['device']} | 数据 {args.data.name}（{len(rows)} 条）| {args.perms} 排列\n")

    summary: list[tuple[str, str, int, float]] = []

    for crit_name in args.criteria.split(","):
        crit_name = crit_name.strip()
        criterion = CRITERIA.get(crit_name, crit_name)
        for name in args.variants.split(","):
            name = name.strip()
            if name not in VARIANTS:
                print(f"跳过未知变体 {name}")
                continue
            descriptions, title = VARIANTS[name]
            labels = build_labels(descriptions)

            hits = 0
            latencies: list[float] = []
            misses: list[str] = []
            for row in rows:
                result = engine.choose(row["text"], labels, criterion, permutations=args.perms)
                latencies.append(result["forward_ms"])
                ok = result["winner"] == row["label"]
                hits += ok
                if not ok:
                    misses.append(f"{row['id']}:{row['label']}->{result['winner']}")

            latencies.sort()
            median = latencies[len(latencies) // 2]
            print(f"=== [{crit_name}] {name}（{title}）: {hits}/{len(rows)} = {hits / len(rows) * 100:.0f}%  中位 {median:.0f} ms ===")
            if misses:
                print("    错例: " + " ".join(misses[:10]))
            print()
            summary.append((crit_name, name, hits, median))

    print("===== 汇总 =====")
    for crit_name, name, hits, median in sorted(summary, key=lambda x: -x[2]):
        print(f"  [{crit_name:<9}] {name:<12} {hits:>2}/{len(rows)} = {hits / len(rows) * 100:3.0f}%   中位 {median:5.0f} ms")


if __name__ == "__main__":
    main()
