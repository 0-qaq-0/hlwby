"""泄漏检查器自己的行为。

检查器写错了比不写更糟 —— 它会给你一个「通过」的假安心。
所以这里把它的**边界**也测了。
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _load():
    path = PROJECT_ROOT / "scripts" / "leak_check.py"
    spec = importlib.util.spec_from_file_location("leak_check", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


leak = _load()


class TestNormalize(unittest.TestCase):
    def test_strips_punctuation_and_space(self):
        self.assertEqual(leak.normalize("嗯嗯，受教了。"), "嗯嗯受教了")
        self.assertEqual(leak.normalize("A B-C"), "ABC")

    def test_keeps_cjk_and_alnum(self):
        self.assertEqual(leak.normalize("第1条 abc"), "第1条abc")


class TestOverlap(unittest.TestCase):
    def test_identical_text_is_one(self):
        text = "追星的都是脑残，这点没什么好争的。"
        self.assertAlmostEqual(leak.overlap(text, text, 8), 1.0)

    def test_unrelated_text_is_zero(self):
        self.assertAlmostEqual(
            leak.overlap("需求根本没起来，供给倒先堆上来了。", "行，你赢了。", 8), 0.0
        )

    def test_short_query_uses_its_own_length_as_window(self):
        """回归：第一版对短句直接返回 0，等于漏检。

        「嗯嗯，受教了。」只有 5 个字，凑不出 8-gram ——
        而「麻」这个词的**全部形态**就是这种短句，漏掉等于没查。
        """
        self.assertAlmostEqual(leak.overlap("嗯嗯，受教了。", "例：「嗯嗯，受教了。」", 8), 1.0)

    def test_too_short_query_is_skipped(self):
        """比 MIN_WINDOW 还短的句子没有区分度，宁可放过不要误报。"""
        self.assertAlmostEqual(leak.overlap("好的", "好的好的好的", 8), 0.0)

    def test_direction_is_query_into_haystack(self):
        """方向是单向的：只问「这句测试句是不是抄了锚点」。"""
        short = "苹果的生态就是比安卓好用"
        long = short + "，用过就知道了，别不服气。这是另一段很长的锚点描述。"
        self.assertGreater(leak.overlap(short, long, 8), 0.5)
        # 反过来问「长的是不是抄了短的」，比例应该低得多
        self.assertLess(leak.overlap(long, short, 8), 0.5)


class TestVerdict(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(leak.verdict(0.0), "ok")
        self.assertEqual(leak.verdict(leak.WARN_THRESHOLD), "warn")
        self.assertEqual(leak.verdict(leak.LEAK_THRESHOLD), "LEAK")

    def test_thresholds_are_ordered(self):
        self.assertLess(leak.WARN_THRESHOLD, leak.LEAK_THRESHOLD)

    def test_min_window_is_sane(self):
        """窗口太小会满屏误报，太大则短句全漏。"""
        self.assertGreaterEqual(leak.MIN_WINDOW, 4)
        self.assertLessEqual(leak.MIN_WINDOW, 8)


class TestWorstAgainst(unittest.TestCase):
    def test_finds_the_matching_label(self):
        score, who = leak.worst_against("嗯嗯，受教了。", 8)
        self.assertEqual(who, "麻")
        self.assertGreaterEqual(score, leak.LEAK_THRESHOLD)

    def test_returns_dash_when_nothing_matches(self):
        _, who = leak.worst_against("zzz qqq 123", 8)
        self.assertEqual(who, "—")


if __name__ == "__main__":
    unittest.main()
