"""页面与「头条数字」的一致性。

回归的是这一件事：**页面上曾经写死「干净测试集 24 条实测 96%」**，
而那时测试集早就是 52 条、真实水平 80.8% 了 —— 一个作废的数字在首页挂了很久。

现在数字只有一个出处（`data/eval_result.json` → `/api/eval` → 页面），
这组测试保证它不会退回去。
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

HTML = (PROJECT_ROOT / "web" / "index.html").read_text(encoding="utf-8")
RESULT = PROJECT_ROOT / "data" / "eval_result.json"


class TestNoHardcodedNumbers(unittest.TestCase):
    def test_no_sample_count_or_accuracy_in_markup(self):
        visible = re.sub(r"<!--.*?-->", "", HTML, flags=re.S)
        visible = re.sub(r"/\*.*?\*/", "", visible, flags=re.S)
        visible = "\n".join(
            line for line in visible.splitlines() if not line.strip().startswith("//")
        )
        for pattern in (r"\d+\s*条实测", r"实测\s*<b[^>]*>\s*\d"):
            with self.subTest(pattern=pattern):
                self.assertIsNone(
                    re.search(pattern, visible),
                    f"页面又硬编码了头条数字（/{pattern}/）—— 应该走 /api/eval",
                )

    def test_placeholders_exist(self):
        self.assertIn('id="eval-accuracy"', HTML)
        self.assertIn('id="eval-detail"', HTML)

    def test_page_fetches_the_eval_endpoint(self):
        self.assertIn("/api/eval", HTML)


class TestAttributionOnPage(unittest.TestCase):
    """页面上的归属说法不能退回「开源版 Jev」。"""

    def test_no_false_attribution(self):
        for pattern in (r"开源版\s*Jev", r"Jev\s*模型开源版"):
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, HTML))

    def test_says_it_is_independent(self):
        self.assertIn("独立", HTML)
        self.assertIn("无隶属关系", HTML)


class TestEvalResultFile(unittest.TestCase):
    """`data/eval_result.json` 是页面数字的唯一出处，格式得钉住。"""

    def setUp(self):
        if not RESULT.is_file():
            self.skipTest("还没跑过 evaluate.py --write-result")
        self.data = json.loads(RESULT.read_text(encoding="utf-8"))

    def test_shape(self):
        for key in ("dataset", "permutations", "total", "correct", "accuracy", "ci95"):
            with self.subTest(key=key):
                self.assertIn(key, self.data)

    def test_accuracy_matches_counts(self):
        self.assertAlmostEqual(
            self.data["accuracy"], self.data["correct"] / self.data["total"], places=4
        )

    def test_ci_brackets_the_accuracy(self):
        low, high = self.data["ci95"]
        self.assertLessEqual(low, self.data["accuracy"])
        self.assertGreaterEqual(high, self.data["accuracy"])

    def test_points_at_the_clean_set(self):
        self.assertIn("eval_clean", self.data["dataset"])

    def test_total_matches_the_actual_file(self):
        """记录里的样本量必须等于干净集现在的行数 —— 否则说明忘了重跑。"""
        rows = [
            line
            for line in (PROJECT_ROOT / "data" / "eval_clean.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
        self.assertEqual(self.data["total"], len(rows))


if __name__ == "__main__":
    unittest.main()
