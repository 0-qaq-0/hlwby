"""泄漏检查器自己的行为。

检查器写错了比不写更糟 —— 它会给你一个「通过」的假安心。
所以这里把它的**边界**也测了。

从 v4 起度量本体搬到了 `tiaoyige/textcheck.py`（页面上的词表编辑器要用同一套，
不然「命令行说没泄漏」和「页面没报警」会是两个标准），
`scripts/leak_check.py` 只剩一层命令行外壳。所以下面测的是**本体**，
另外再钉一条「外壳和本体必须是同一套阈值」。
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tiaoyige import textcheck  # noqa: E402


def _load_script():
    path = PROJECT_ROOT / "scripts" / "leak_check.py"
    spec = importlib.util.spec_from_file_location("leak_check_script", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestNormalize(unittest.TestCase):
    def test_strips_punctuation_and_space(self):
        self.assertEqual(textcheck.normalize("嗯嗯，受教了。"), "嗯嗯受教了")
        self.assertEqual(textcheck.normalize("A B-C"), "ABC")

    def test_keeps_cjk_and_alnum(self):
        self.assertEqual(textcheck.normalize("第1条 abc"), "第1条abc")

    def test_handles_none(self):
        self.assertEqual(textcheck.normalize(None), "")


class TestOverlap(unittest.TestCase):
    def test_identical_text_is_one(self):
        text = "追星的都是脑残，这点没什么好争的。"
        self.assertAlmostEqual(textcheck.overlap(text, text, 8), 1.0)

    def test_unrelated_text_is_zero(self):
        self.assertAlmostEqual(
            textcheck.overlap("需求根本没起来，供给倒先堆上来了。", "行，你赢了。", 8), 0.0
        )

    def test_short_query_uses_its_own_length_as_window(self):
        """回归：第一版对短句直接返回 0，等于漏检。

        「嗯嗯，受教了。」只有 5 个字，凑不出 8-gram ——
        而「麻」这个词的**全部形态**就是这种短句，漏掉等于没查。
        """
        self.assertAlmostEqual(
            textcheck.overlap("嗯嗯，受教了。", "例：「嗯嗯，受教了。」", 8), 1.0
        )

    def test_too_short_query_is_skipped(self):
        """比 MIN_WINDOW 还短的句子没有区分度，宁可放过不要误报。"""
        self.assertAlmostEqual(textcheck.overlap("好的", "好的好的好的", 8), 0.0)

    def test_direction_is_query_into_haystack(self):
        """方向是单向的：只问「这句测试句是不是抄了锚点」。"""
        short = "苹果的生态就是比安卓好用"
        long = short + "，用过就知道了，别不服气。这是另一段很长的锚点描述。"
        self.assertGreater(textcheck.overlap(short, long, 8), 0.5)
        # 反过来问「长的是不是抄了短的」，比例应该低得多
        self.assertLess(textcheck.overlap(long, short, 8), 0.5)


class TestVerdict(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(textcheck.verdict(0.0), "ok")
        self.assertEqual(textcheck.verdict(textcheck.WARN_THRESHOLD), "warn")
        self.assertEqual(textcheck.verdict(textcheck.LEAK_THRESHOLD), "LEAK")

    def test_thresholds_are_ordered(self):
        self.assertLess(textcheck.WARN_THRESHOLD, textcheck.LEAK_THRESHOLD)

    def test_min_window_is_sane(self):
        """窗口太小会满屏误报，太大则短句全漏。"""
        self.assertGreaterEqual(textcheck.MIN_WINDOW, 4)
        self.assertLessEqual(textcheck.MIN_WINDOW, 8)


class TestWorstAgainst(unittest.TestCase):
    def test_finds_the_matching_label(self):
        descriptions = {"麻": "例：「嗯嗯，受教了。」", "赢": "例：「人最大的敌人，从来都是自己」"}
        score, who = textcheck.worst_against("嗯嗯，受教了。", descriptions, 8)
        self.assertEqual(who, "麻")
        self.assertGreaterEqual(score, textcheck.LEAK_THRESHOLD)

    def test_returns_dash_when_nothing_matches(self):
        _, who = textcheck.worst_against("zzz qqq 123", {"麻": "例：「嗯嗯，受教了。」"}, 8)
        self.assertEqual(who, "—")

    def test_empty_descriptions(self):
        self.assertEqual(textcheck.worst_against("随便一句", {}, 8), (0.0, "—"))


class TestScriptMatchesModule(unittest.TestCase):
    """`scripts/leak_check.py` 只是外壳 —— 它必须和本体是同一套阈值和实现。

    否则会出现「命令行说没泄漏、页面上却报警」这种最让人不信任的分裂。
    """

    @classmethod
    def setUpClass(cls):
        cls.script = _load_script()

    def test_thresholds_are_shared(self):
        self.assertEqual(self.script.LEAK_THRESHOLD, textcheck.LEAK_THRESHOLD)
        self.assertEqual(self.script.WARN_THRESHOLD, textcheck.WARN_THRESHOLD)

    def test_overlap_is_the_same_function(self):
        self.assertIs(self.script.overlap, textcheck.overlap)

    def test_verdict_is_the_same_function(self):
        self.assertIs(self.script.verdict, textcheck.verdict)

    def test_worst_against_still_knows_the_bayi_labels(self):
        score, who = self.script.worst_against("嗯嗯，受教了。", 8)
        self.assertEqual(who, "麻")
        self.assertGreaterEqual(score, textcheck.LEAK_THRESHOLD)


if __name__ == "__main__":
    unittest.main()
