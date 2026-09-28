"""字面重合度：判断两段中文文本有没有在「抄同一句话」。

这套度量原来长在 `scripts/leak_check.py` 里，只服务于一个用途：检查
`data/eval_clean.jsonl` 有没有抄锚点例句。现在「自定义判断类型」也能在页面里
改锚点了，所以同一套度量得能在**运行时**用 —— 用户刚敲进去的锚点和他自己
写的示例之间有没有互相抄，跟当年那 14 条泄漏是同一个问题。

抽出来之后 `scripts/leak_check.py` 只是它的一层命令行外壳，两边永远是同一套算法。

## 度量本身

两边都只留中英文数字（去掉标点、空白），再比字符 n-gram 的集合重合率。
分母取**较短一侧**的 n-gram 数量 —— 否则长描述天然占便宜：
一句 20 字的示例对上一段 120 字的锚点，重合率会被稀释成 0。

方向也是单向的：我们关心「这句示例是不是抄了锚点」，而不是反过来。
"""

from __future__ import annotations

import re

#: 只留中英文数字，标点空白全部丢掉 —— 泄漏往往是「同一句话改了标点」。
_KEEP = re.compile(r"[^\u4e00-\u9fffA-Za-z0-9]")

#: 默认的 n-gram 窗口。
DEFAULT_N = 8

#: >= 0.30 判定为泄漏：这句话基本能在锚点里逐字找到。
LEAK_THRESHOLD = 0.30

#: >= 0.15 判可疑，人工看一眼。
WARN_THRESHOLD = 0.15

#: 比这个还短的窗口就没有区分度了（「嗯嗯受教了」这种 5 字句会整个命中）。
MIN_WINDOW = 5


def normalize(text: str) -> str:
    """去掉标点、空白、换行，只留中英文数字。"""
    return _KEEP.sub("", text or "")


def overlap(query: str, haystack: str, n: int = DEFAULT_N) -> float:
    """``query`` 里有多大比例的字面片段能在 ``haystack`` 里逐字找到。

    窗口大小取 ``min(n, len(query))`` —— 否则像「嗯嗯，受教了。」这种 5 字短句
    永远凑不出 8-gram，会从检查里溜过去（这是本算法第一版的 bug，
    短句正是「麻」这个词的全部形态，漏掉等于没查）。
    """
    q = normalize(query)
    if not q:
        return 0.0
    width = min(n, len(q))
    if width < MIN_WINDOW:
        # 句子太短，任何片段都不足以说明问题 —— 宁可放过，不要误报。
        return 0.0
    grams = {q[i : i + width] for i in range(len(q) - width + 1)}
    hay = normalize(haystack)
    hits = sum(1 for gram in grams if gram in hay)
    return hits / len(grams)


def worst_against(
    text: str, descriptions: dict[str, str], n: int = DEFAULT_N
) -> tuple[float, str]:
    """这句话和哪个锚点最像，像到什么程度。

    ``descriptions`` 是 ``{标签 id: 锚点描述}``。返回 ``(重合度, 标签 id)``；
    一个都没有时返回 ``(0.0, "—")``。
    """
    best, who = 0.0, "—"
    for label_id, description in descriptions.items():
        score = overlap(text, description, n)
        if score > best:
            best, who = score, label_id
    return best, who


def verdict(score: float) -> str:
    """把重合度翻译成 ``ok`` / ``warn`` / ``LEAK``。"""
    if score >= LEAK_THRESHOLD:
        return "LEAK"
    if score >= WARN_THRESHOLD:
        return "warn"
    return "ok"


__all__ = [
    "DEFAULT_N",
    "LEAK_THRESHOLD",
    "MIN_WINDOW",
    "WARN_THRESHOLD",
    "normalize",
    "overlap",
    "verdict",
    "worst_against",
]
