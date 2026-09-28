"""中文输出在「控制台不是 UTF-8」的机器上不许崩。

## 回归的是这件事

release 工作流第一次跑：ubuntu 的构建 job 成功，**windows-latest 失败**，
日志里只有一句 `Process completed with exit code 1` —— 因为
`print("[build] 版本 …")` 在 cp1252 的 stdout 上直接抛 `UnicodeEncodeError`，
而那条异常信息本身也是中文，于是连报错都打不出来。

本地怎么试都好：本地是 cp936，中文编得进去。这类 bug 只在 CI、重定向到文件、
或者被别的程序捕获输出时出现 —— 恰好是最不容易当场发现的那几种。

所以这里**真的用一个 cp1252 的子进程**去跑，而不是只检查源码里有没有那行调用。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tiaoyige.console import enable_utf8  # noqa: E402


class TestEnableUtf8(unittest.TestCase):
    def test_is_idempotent_and_never_raises(self):
        """重复调、或者流不支持重配置时，都不该抛异常。"""
        enable_utf8()
        enable_utf8()

    def test_returns_bool(self):
        self.assertIsInstance(enable_utf8(), bool)


class TestScriptsUnderNonUtf8Stdout(unittest.TestCase):
    """在 cp1252 的 stdout 下跑真实脚本 —— 这是 CI 上翻车的那条路径。"""

    def run_script(self, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
        env = {**os.environ, "PYTHONIOENCODING": "cp1252"}
        return subprocess.run(
            [sys.executable, *args],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            timeout=300,
        )

    def test_build_release_prints_chinese_under_cp1252(self):
        """构建脚本刻意不 import tiaoyige，所以它得自己修 stdout。"""
        with tempfile.TemporaryDirectory(prefix="tiaoyige-encoding-") as tmp:
            result = self.run_script(
                [str(PROJECT_ROOT / "scripts" / "build_release.py"), "--out", tmp, "--platform", "win64"],
                cwd=PROJECT_ROOT,
            )
            stderr = result.stderr.decode("utf-8", "replace")
            self.assertEqual(result.returncode, 0, f"构建在 cp1252 下失败了：\n{stderr}")
            self.assertIn("[build]", result.stdout.decode("utf-8", "replace"))
            self.assertNotIn("UnicodeEncodeError", stderr)

    def test_package_entry_points_do_not_crash(self):
        """import 了 tiaoyige 的脚本靠包里的 import 钩子自动修好。"""
        for script, args in [
            ("scripts/profiles_check.py", []),
            ("scripts/page_check.py", []),
            ("scripts/labels_check.py", []),
            ("scripts/docs_check.py", []),
        ]:
            with self.subTest(script=script):
                result = self.run_script([str(PROJECT_ROOT / script), *args], cwd=PROJECT_ROOT)
                stderr = result.stderr.decode("utf-8", "replace")
                self.assertNotIn("UnicodeEncodeError", stderr, f"{script} 在 cp1252 下炸了")
                self.assertIn(result.returncode, (0, 1), f"{script} 异常退出：{stderr}")

    def test_server_help_works(self):
        result = self.run_script(["-m", "tiaoyige.server", "--help"], cwd=PROJECT_ROOT)
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))


if __name__ == "__main__":
    unittest.main()
