"""页面与「头条数字」的一致性。

回归的是这一件事：**页面上曾经写死「干净测试集 24 条实测 96%」**，
而那时测试集早就是 52 条、真实水平是另一个数了 —— 一个作废的数字在首页挂了很久。

现在数字只有一个出处（`data/eval_result.json` → `/api/eval` → 页面），
这组测试保证它不会退回去。

从 v4 起页面拆成了多文件（`web/index.html` + `web/style.css` + `web/js/**`），
所以这里除了数字检查，还多了一组**静态装配检查**：JS 里 `$("x")` 引用的 id
必须在 HTML 里存在，模块之间的相对 import 必须指向真实文件。
少一个 id 就是运行时的 null 崩溃，这种错不该等到有人点开页面才发现。
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

WEB = PROJECT_ROOT / "web"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
MODULES = {path: path.read_text(encoding="utf-8") for path in sorted((WEB / "js").rglob("*.js"))}
ALL_JS = "\n".join(MODULES.values())
RESULT = PROJECT_ROOT / "data" / "eval_result.json"


def strip_comments(source: str) -> str:
    source = re.sub(r"<!--.*?-->", "", source, flags=re.S)
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return "\n".join(
        line for line in source.splitlines() if not line.strip().startswith("//")
    )


class TestNoHardcodedNumbers(unittest.TestCase):
    def test_no_sample_count_or_accuracy_in_markup(self):
        for name, source in [("index.html", HTML), *[(str(p.relative_to(WEB)), s) for p, s in MODULES.items()]]:
            visible = strip_comments(source)
            for pattern in (
                r"\d+\s*条实测",
                r"实测\s*<b[^>]*>\s*\d",
                r"(准确率|accuracy)[^\"'\n]{0,24}\d+(?:\.\d+)?\s*%",
            ):
                with self.subTest(file=name, pattern=pattern):
                    self.assertIsNone(
                        re.search(pattern, visible),
                        f"web/{name} 又硬编码了头条数字（/{pattern}/）—— 应该走 /api/eval",
                    )

    def test_placeholders_exist(self):
        self.assertIn('id="eval-accuracy"', HTML)
        self.assertIn('id="eval-detail"', HTML)

    def test_page_fetches_the_eval_endpoint(self):
        self.assertIn("/api/eval", ALL_JS)


class TestAttributionOnPage(unittest.TestCase):
    """页面上的归属说法不能退回「开源版 Jev」。"""

    def test_no_false_attribution(self):
        for name, source in [("index.html", HTML), *[(str(p.relative_to(WEB)), s) for p, s in MODULES.items()]]:
            for pattern in (r"开源版\s*Jev", r"Jev\s*模型开源版"):
                with self.subTest(file=name, pattern=pattern):
                    self.assertIsNone(re.search(pattern, source))

    def test_says_it_is_independent(self):
        self.assertIn("独立", HTML)
        self.assertIn("无隶属关系", HTML)


class TestPageAssembly(unittest.TestCase):
    """多文件前端的静态装配检查 —— 等价于 `scripts/page_check.py` 的核心那几条。"""

    REQUIRED = [
        "index.html",
        "style.css",
        "js/main.js",
        "js/api.js",
        "js/util.js",
        "js/state.js",
        "js/tabs/judge.js",
        "js/tabs/editor.js",
        "js/tabs/eval.js",
        "js/tabs/settings.js",
    ]

    def test_all_files_exist(self):
        for name in self.REQUIRED:
            with self.subTest(file=name):
                self.assertTrue((WEB / name).is_file(), f"缺少 web/{name}")

    def test_entry_is_a_module(self):
        self.assertIn('<script type="module" src="/js/main.js">', HTML)
        self.assertIn('href="/style.css"', HTML)

    def test_js_referenced_ids_exist_in_html(self):
        html_ids = set(re.findall(r'id="([^"]+)"', HTML))
        js_ids = set()
        for source in MODULES.values():
            js_ids |= set(re.findall(r'\$\("([^"]+)"\)', source))
            js_ids |= set(re.findall(r'getElementById\("([^"]+)"\)', source))
        missing = sorted(js_ids - html_ids)
        self.assertEqual(missing, [], f"JS 引用了 HTML 里没有的 id：{missing}")

    def test_relative_imports_resolve(self):
        for path, source in MODULES.items():
            for target in re.findall(r'from\s+"(\.[^"]+)"', source):
                with self.subTest(module=path.name, target=target):
                    self.assertTrue((path.parent / target).resolve().is_file())

    def test_four_tabs_are_wired(self):
        for tab in ("judge", "labels", "eval", "settings"):
            with self.subTest(tab=tab):
                self.assertIn(f'data-tab="{tab}"', HTML)
                self.assertIn(f'data-panel="{tab}"', HTML)

    def test_no_leftover_inline_script(self):
        """拆成模块之后，index.html 里不该再有内联脚本 —— 逻辑只住一个地方。"""
        self.assertNotIn("<script>", HTML)


class TestEvalResultFile(unittest.TestCase):
    """评测结果文件是页面数字的唯一出处，格式得钉住。"""

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

    def test_belongs_to_the_default_profile(self):
        """`data/eval_result.json` 是「八艺」的成绩，别被别的类型顶掉。"""
        self.assertEqual(self.data.get("profile", "bayi"), "bayi")

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
