"""引擎里不碰 GPU 的那部分纯函数。

这些函数不加载模型，所以**秒回**，适合放进 CI。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from jev_meme.engine import (  # noqa: E402
    DEFAULT_PERMUTATIONS,
    TOKEN_BUDGET,
    adaptive_permutations,
    permutations_of,
)
from jev_meme.labels import MEME_LABELS  # noqa: E402


class TestPermutations(unittest.TestCase):
    def test_single(self):
        self.assertEqual(permutations_of(MEME_LABELS, 1), [list(MEME_LABELS)])

    def test_count(self):
        for count in (2, 3, 5, 7, 8):
            with self.subTest(count=count):
                self.assertEqual(len(permutations_of(MEME_LABELS, count)), count)

    def test_first_is_original_second_is_reversed(self):
        orders = permutations_of(MEME_LABELS, 5)
        self.assertEqual([x["id"] for x in orders[0]], [x["id"] for x in MEME_LABELS])
        self.assertEqual(
            [x["id"] for x in orders[1]], [x["id"] for x in reversed(MEME_LABELS)]
        )

    def test_each_order_is_a_permutation_of_the_same_set(self):
        """每种排列都得是同一批标签的重排，不能多也不能少。"""
        expected = sorted(label["id"] for label in MEME_LABELS)
        for order in permutations_of(MEME_LABELS, 7):
            with self.subTest(order=[x["id"] for x in order]):
                self.assertEqual(sorted(x["id"] for x in order), expected)

    def test_deterministic(self):
        """固定 seed —— 同一个输入必须永远得到同一个答案。"""
        a = [[x["id"] for x in order] for order in permutations_of(MEME_LABELS, 5)]
        b = [[x["id"] for x in order] for order in permutations_of(MEME_LABELS, 5)]
        self.assertEqual(a, b)

    def test_does_not_mutate_input(self):
        before = [label["id"] for label in MEME_LABELS]
        permutations_of(MEME_LABELS, 7)
        self.assertEqual([label["id"] for label in MEME_LABELS], before)


class TestAdaptivePermutations(unittest.TestCase):
    """长输入自动降档。默认档必须真的是默认档，别被悄悄压掉。"""

    def test_short_input_keeps_requested(self):
        # 一句话评论的 prompt 大约 1000 token。
        self.assertEqual(adaptive_permutations(1000, 3), 3)
        self.assertEqual(adaptive_permutations(1000, 5), 5)
        self.assertEqual(adaptive_permutations(1000, 7), 7)

    def test_never_below_one(self):
        self.assertEqual(adaptive_permutations(99999, 7), 1)
        self.assertEqual(adaptive_permutations(1, 0), 1)

    def test_never_above_requested(self):
        for tokens in (100, 500, 1000, 2000, 4000):
            with self.subTest(tokens=tokens):
                self.assertLessEqual(adaptive_permutations(tokens, 5), 5)

    def test_default_budget_covers_a_typical_comment(self):
        """回归：TOKEN_BUDGET 曾经设得太小，把「更稳」档悄悄压成了 5 排列。

        八个字的锚点例句加起来约 950 token，所以哪怕评论只有一句话，
        prompt 也有 1000 token 左右。预算必须容得下默认档。
        """
        self.assertGreaterEqual(TOKEN_BUDGET // 1000, DEFAULT_PERMUTATIONS)

    def test_monotone_in_length(self):
        """输入越长，能跑的排列数不该变多。"""
        values = [adaptive_permutations(tokens, 7) for tokens in (500, 1000, 2000, 4000)]
        self.assertEqual(values, sorted(values, reverse=True))


class TestModelChoices(unittest.TestCase):
    def test_every_choice_has_a_revision(self):
        from jev_meme.engine import MODEL_CHOICES

        self.assertIn("qwen3.5-2b", MODEL_CHOICES)
        for name, (directory, revision) in MODEL_CHOICES.items():
            with self.subTest(model=name):
                self.assertTrue(directory)
                self.assertRegex(revision, r"^[0-9a-f]{40}$")


if __name__ == "__main__":
    unittest.main()
