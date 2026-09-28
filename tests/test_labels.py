"""词表与页面示例的硬约束。

这些东西一旦破了，系统会**安静地**变差（准确率掉、页面看起来像坏的），
所以必须有测试兜着。
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from biaochi.labels import CRITERION, EXAMPLES, LABEL_IDS, MEME_LABELS  # noqa: E402

EXPECTED_ORDER = "典孝急乐蚌批赢麻"


def _load_leak_check():
    """把 scripts/leak_check.py 当模块加载（scripts/ 不是包）。"""
    path = PROJECT_ROOT / "scripts" / "leak_check.py"
    spec = importlib.util.spec_from_file_location("leak_check", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestLabelSet(unittest.TestCase):
    def test_order_and_count(self):
        self.assertEqual("".join(LABEL_IDS), EXPECTED_ORDER)
        self.assertEqual(len(MEME_LABELS), 8)

    def test_ids_unique(self):
        self.assertEqual(len(set(LABEL_IDS)), len(LABEL_IDS))

    def test_every_label_has_an_example(self):
        """锚点里必须有「例：」—— 实测「给例句」比「写抽象定义」准得多。"""
        for label in MEME_LABELS:
            with self.subTest(label=label["id"]):
                self.assertIn("例：", label["description"])
                self.assertGreater(len(label["description"]), 40)
                self.assertTrue(label["hint"].strip())
                self.assertTrue(label["pinyin"].strip())
                self.assertRegex(label["accent"], r"^#[0-9a-fA-F]{6}$")

    def test_criterion_is_not_empty(self):
        self.assertIn("八艺", CRITERION)

    def test_no_generic_shape_descriptor_in_dian(self):
        """「典」的描述里不能出现泛化的形状描述。

        实测（scripts/anchor_tune.py，52 条干净集，5 排列）：
        加一句「一段不长不短的普通论述」会让准确率从 80.8% 掉到 73.1%，
        错例塌缩到「典」的从 3 个涨到 10 个。这是有剂量反应的，
        所以拿测试钉住它，别让人顺手加回去。
        """
        dian = next(label for label in MEME_LABELS if label["id"] == "典")
        for banned in ("普通论述", "不长不短", "正常的、有内容的发言"):
            with self.subTest(banned=banned):
                self.assertNotIn(banned, dian["description"])


class TestPageExamples(unittest.TestCase):
    def test_covers_every_label_exactly_once(self):
        self.assertEqual({e["label"] for e in EXAMPLES}, set(LABEL_IDS))
        self.assertEqual(len(EXAMPLES), len(LABEL_IDS))

    def test_no_duplicate_text(self):
        self.assertEqual(len({e["text"] for e in EXAMPLES}), len(EXAMPLES))

    def test_no_literal_leak_against_anchors(self):
        """页面示例不能是锚点例句的复制品 —— 那是自问自答。

        回归用例：原来「麻」的示例是「那可能是我理解偏了，打扰了。」，
        和锚点里的例句一字不差，重合度 1.00。
        """
        leak = _load_leak_check()
        for example in EXAMPLES:
            score, who = leak.worst_against(example["text"], 8)
            with self.subTest(label=example["label"]):
                self.assertLess(
                    score,
                    leak.LEAK_THRESHOLD,
                    f"页面示例「{example['text']}」与锚点「{who}」重合 {score:.2f}",
                )


class TestEvalSets(unittest.TestCase):
    """测试集的完整性。干净集一旦被泄漏污染，准确率就是假的。"""

    def setUp(self):
        self.leak = _load_leak_check()
        self.data = PROJECT_ROOT / "data"

    def test_clean_set_has_no_leak(self):
        rows = self.leak.load_rows(self.data / "eval_clean.jsonl")
        self.assertGreater(len(rows), 0, "干净集不能为空")
        for row in rows:
            score, who = self.leak.worst_against(row["text"], 8)
            with self.subTest(id=row["id"]):
                self.assertLess(
                    score,
                    self.leak.LEAK_THRESHOLD,
                    f"{row['id']} 与锚点「{who}」重合 {score:.2f} —— 干净集被污染了",
                )

    def test_clean_set_covers_every_label(self):
        rows = self.leak.load_rows(self.data / "eval_clean.jsonl")
        self.assertEqual({row["label"] for row in rows}, set(LABEL_IDS))

    def test_ids_unique_within_each_file(self):
        for name in ("eval_clean", "eval_overlap"):
            rows = self.leak.load_rows(self.data / f"{name}.jsonl")
            ids = [row["id"] for row in rows]
            with self.subTest(dataset=name):
                self.assertEqual(len(set(ids)), len(ids))

    def test_ids_do_not_collide_across_files(self):
        """两个文件的 id 不能撞车。

        回归用例：原来两套集子都叫 `dian-1`…`ma-3`，但文本完全不同，
        合并分析时会静默串味。现在对照集统一加 `ov-` / `leaked-` 前缀。
        """
        clean = {row["id"] for row in self.leak.load_rows(self.data / "eval_clean.jsonl")}
        overlap = {row["id"] for row in self.leak.load_rows(self.data / "eval_overlap.jsonl")}
        self.assertEqual(clean & overlap, set())

    def test_overlap_set_keeps_the_leaked_rows(self):
        """泄漏样本必须留在对照集里，别删 —— 它们是「泄漏长什么样」的证据。"""
        overlap = self.leak.load_rows(self.data / "eval_overlap.jsonl")
        leaked = [row for row in overlap if row["id"].startswith("leaked-")]
        self.assertGreaterEqual(len(leaked), 10)
        for row in leaked:
            score, _ = self.leak.worst_against(row["text"], 8)
            with self.subTest(id=row["id"]):
                self.assertGreaterEqual(score, self.leak.LEAK_THRESHOLD)

    def test_semantic_prefix_documents_the_checkers_blind_spot(self):
        """`semantic-` 前缀的行**故意**不被字面检查抓到。

        它们和锚点意思一样但换了说法（例如锚点讲「熵减过程」，它讲「熵增定律」）。
        这个测试不是挑刺，是把检查器的**已知盲区**钉在测试里 ——
        哪天有人以为「leak_check 通过 = 没泄漏」，这里会提醒他没这回事。
        """
        overlap = self.leak.load_rows(self.data / "eval_overlap.jsonl")
        semantic = [row for row in overlap if row["id"].startswith("semantic-")]
        self.assertGreaterEqual(len(semantic), 1)
        for row in semantic:
            score, _ = self.leak.worst_against(row["text"], 8)
            with self.subTest(id=row["id"]):
                self.assertLess(score, self.leak.LEAK_THRESHOLD)


if __name__ == "__main__":
    unittest.main()
