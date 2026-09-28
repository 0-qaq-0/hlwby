"""release 包构建器自己的行为。

为什么要给「打包」写测试：包是**唯一**会离开这个仓库的东西 —— 用户下载它、
校验它、双击它。包里少一个文件，在用户那边就是「双击没反应」；包里多带了
用户自己的词表，那是把别人的数据发出去了。这些都不是本地跑一遍服务能发现的。

所以这里断言四件事：
  * 必须有的在、不该有的不在
  * manifest 里的 sha256 和包里实际内容对得上（校验下载完整性的承诺）
  * 两次构建的 manifest 一模一样（可重复构建的回归）
  * 解压出来的包能 import（证明 vendor 子集挑得够）

刻意用标准库 unittest、不联网、不加载模型、不占显存：整个文件跑完应该在一两秒
量级 —— 不然没人会在改完一行之后跑它。
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from biaochi.version import __version__ as VERSION  # noqa: E402


def _load_build_module():
    """scripts/ 不是包（没有 __init__.py），所以按文件路径加载。"""
    path = PROJECT_ROOT / "scripts" / "build_release.py"
    spec = importlib.util.spec_from_file_location("build_release", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build = _load_build_module()

TOP = f"biaochi-{VERSION}"

#: 包里必须有的东西。挑的是「少了用户就跑不起来 / 就没法校验」的那些：
#: 服务代码、页面、启动器、模型下载器、vendor 引擎、许可、版本号、清单。
REQUIRED_FILES = (
    "biaochi/__init__.py",
    "biaochi/engine.py",
    "biaochi/server.py",
    "biaochi/version.py",
    "biaochi/labels.py",
    "web/index.html",
    "scripts/build_release.py",
    "scripts/launch.ps1",
    "scripts/download_model.py",
    "tests/__init__.py",
    "data/eval_clean.jsonl",
    "data/eval_result.json",
    "vendor/SemIf-OpenJev/LICENSE",
    "vendor/SemIf-OpenJev/README.md",
    "vendor/SemIf-OpenJev/pyproject.toml",
    "vendor/SemIf-OpenJev/src/semif_phase1/core.py",
    "vendor/SemIf-OpenJev/src/semif_phase1/direct.py",
    "requirements.txt",
    "LICENSE",
    "README.md",
    "README-启动.md",
    "docs/RELEASE.md",
    "一键启动.bat",
    "start.sh",
    "run.ps1",
    "VERSION",
    "release-manifest.json",
)

#: 目录占位：zip 不记录空目录，所以用 .gitkeep 显式占位，
#: 用户解压出来才知道自己的词表该放哪。
PLACEHOLDERS = ("data/profiles/.gitkeep", "data/eval_results/.gitkeep")


class BuildFixture(unittest.TestCase):
    """整个文件共用一次构建结果（构建一次约 0.2 秒，但没必要每个用例都来一遍）。"""

    tmp: tempfile.TemporaryDirectory
    out_dir: Path
    zip_path: Path
    names: list[str]
    manifest: dict

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory(prefix="biaochi-release-test-")
        cls.out_dir = Path(cls.tmp.name) / "dist"
        with redirect_stdout(io.StringIO()):
            code = build.main(["--out", str(cls.out_dir)])
        assert code == 0, "构建失败，后面的断言没有意义"
        cls.zip_path = cls.out_dir / f"{TOP}-{build.default_platform()}.zip"
        with zipfile.ZipFile(cls.zip_path) as archive:
            cls.names = archive.namelist()
            cls.manifest = json.loads(archive.read(f"{TOP}/release-manifest.json"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def read(self, relative: str) -> bytes:
        with zipfile.ZipFile(self.zip_path) as archive:
            return archive.read(f"{TOP}/{relative}")


class TestPackageShape(BuildFixture):
    def test_zip_exists_with_expected_name(self):
        self.assertTrue(self.zip_path.is_file())
        self.assertEqual(self.zip_path.name, f"biaochi-{VERSION}-{build.default_platform()}.zip")

    def test_single_top_level_directory(self):
        """解压不能散落一地 —— 用户是往桌面/下载目录里解压的。"""
        tops = {name.split("/")[0] for name in self.names}
        self.assertEqual(tops, {TOP})

    def test_every_entry_is_inside_the_top_directory(self):
        for name in self.names:
            self.assertTrue(name.startswith(f"{TOP}/"), name)
            self.assertFalse(name.startswith("/"), name)
            self.assertNotIn("..", name.split("/"), name)

    def test_no_directory_entries(self):
        """只写文件条目：目录靠文件路径隐含，空目录用 .gitkeep 占位。"""
        for name in self.names:
            self.assertFalse(name.endswith("/"), name)

    def test_no_duplicate_entries(self):
        self.assertEqual(len(self.names), len(set(self.names)))


class TestRequiredContents(BuildFixture):
    def test_required_files_are_present(self):
        for relative in REQUIRED_FILES:
            self.assertIn(f"{TOP}/{relative}", self.names, f"包里少了 {relative}")

    def test_placeholders_are_present(self):
        for relative in PLACEHOLDERS:
            self.assertIn(f"{TOP}/{relative}", self.names, f"包里少了占位 {relative}")

    def test_version_file_content(self):
        self.assertEqual(self.read("VERSION").decode("utf-8").strip(), VERSION)

    def test_manifest_version_fields(self):
        self.assertEqual(self.manifest["version"], VERSION)
        self.assertEqual(self.manifest["name"], "biaochi")
        self.assertEqual(self.manifest["platform"], build.default_platform())
        self.assertEqual(self.manifest["schema"], build.read_version()[1])


class TestExcludedContents(BuildFixture):
    def test_no_environment_or_git(self):
        for prefix in (".venv/", ".git/", ".cache/", "dist/"):
            self.assertFalse([n for n in self.names if n.startswith(f"{TOP}/{prefix}")], prefix)

    def test_no_model_weights_by_default(self):
        """权重 4.3 GB，永远不该默认进包。"""
        self.assertFalse([n for n in self.names if n.startswith(f"{TOP}/models/")])

    def test_no_pycache_or_pyc(self):
        for name in self.names:
            self.assertNotIn("__pycache__", name)
            self.assertFalse(name.endswith((".pyc", ".pyo")), name)

    def test_no_ci_config(self):
        self.assertFalse([n for n in self.names if n.startswith(f"{TOP}/.github/")])

    def test_no_vendor_bulk_assets(self):
        """上游那 ~30MB 的评测 / benchmark / demo 资产一个都不该进来。"""
        for folder in ("results", "benchmarks", "webgpu-demo", "demo", "assets",
                       "exl3-bridge", "manifests", "tests", "docs", "examples"):
            prefix = f"{TOP}/vendor/SemIf-OpenJev/{folder}/"
            self.assertFalse([n for n in self.names if n.startswith(prefix)], folder)

    def test_no_user_profiles_in_package(self):
        """用户自己存的判断类型是用户数据，不能跟着发行包走。"""
        user_jsons = [
            n for n in self.names
            if n.startswith(f"{TOP}/data/profiles/") and n.endswith(".json")
        ]
        self.assertEqual(user_jsons, [])


class TestExclusionRulesOnSyntheticTree(unittest.TestCase):
    """上面几条断言的是「当前这棵树」的结果，这里直接测规则本身。

    为什么要造假树：真实仓库里没有 .venv/models 之外的大部分东西，
    规则写错了也不会有人发现 —— 直到某天用户拿到一个 4GB 的 zip。
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="biaochi-fake-tree-")
        self.root = Path(self.tmp.name)
        self._real_root = build.PROJECT_ROOT
        build.PROJECT_ROOT = self.root
        self.addCleanup(self._restore)

        for relative in (
            "biaochi/server.py",
            "data/eval_clean.jsonl",
            "data/profiles/我的词表.json",
            "data/profiles/.gitkeep",
            "models/Qwen3.5-2B/model.safetensors",
            ".venv/Scripts/python.exe",
            ".git/config",
            "__pycache__/x.pyc",
            "web/__pycache__/x.pyc",
            "scripts/junk.pyc",
            "dist/biaochi-4.1.0-win64.zip",
            ".github/workflows/release.yml",
            "vendor/SemIf-OpenJev/src/semif_phase1/core.py",
            "vendor/SemIf-OpenJev/results/raw/big.jsonl",
            "vendor/SemIf-OpenJev/webgpu-demo/app.js",
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")

    def _restore(self) -> None:
        build.PROJECT_ROOT = self._real_root
        self.tmp.cleanup()

    def collect(self, with_model: bool = False) -> set[str]:
        out_dir = self.root / "dist"
        return {rel for _, rel in build.collect_files(out_dir, with_model)}

    def test_keeps_wanted_files(self):
        found = self.collect()
        self.assertIn("biaochi/server.py", found)
        self.assertIn("data/eval_clean.jsonl", found)
        self.assertIn("data/profiles/.gitkeep", found)
        self.assertIn("vendor/SemIf-OpenJev/src/semif_phase1/core.py", found)

    def test_drops_junk_and_secrets(self):
        found = self.collect()
        for relative in (
            "data/profiles/我的词表.json",
            "models/Qwen3.5-2B/model.safetensors",
            ".venv/Scripts/python.exe",
            ".git/config",
            "__pycache__/x.pyc",
            "web/__pycache__/x.pyc",
            "scripts/junk.pyc",
            "dist/biaochi-4.1.0-win64.zip",
            ".github/workflows/release.yml",
            "vendor/SemIf-OpenJev/results/raw/big.jsonl",
            "vendor/SemIf-OpenJev/webgpu-demo/app.js",
        ):
            self.assertNotIn(relative, found, relative)

    def test_with_model_keeps_weights(self):
        self.assertIn("models/Qwen3.5-2B/model.safetensors", self.collect(with_model=True))

    def test_with_model_warns_and_packs_weights(self):
        """--with-model 要真的把权重塞进 payload，并且必须警告（体积 + 内存）。"""
        files = build.collect_files(self.root / "dist", True)
        buffer = io.StringIO()
        with redirect_stderr(buffer):
            payload = build.build_payload(files, "4.1.0", 1, "biaochi", "win64", True)
        self.assertIn("models/Qwen3.5-2B/model.safetensors", payload)
        warnings = buffer.getvalue()
        self.assertIn("2GB", warnings)
        self.assertIn("内存", warnings)

    def test_out_dir_is_never_repacked(self):
        """输出目录指向仓库里时，第二次构建不能把上一次的 zip 收进来。"""
        self.assertEqual([p for p in self.collect() if p.startswith("dist/")], [])


class TestManifest(BuildFixture):
    def test_manifest_does_not_list_itself(self):
        paths = [entry["path"] for entry in self.manifest["files"]]
        self.assertNotIn("release-manifest.json", paths)

    def test_files_sorted_and_unique(self):
        paths = [entry["path"] for entry in self.manifest["files"]]
        self.assertEqual(paths, sorted(paths))
        self.assertEqual(len(paths), len(set(paths)))

    def test_counts_match(self):
        entries = self.manifest["files"]
        self.assertEqual(self.manifest["file_count"], len(entries))
        self.assertEqual(self.manifest["total_bytes"], sum(e["bytes"] for e in entries))
        self.assertGreater(len(entries), 30)

    def test_built_at_is_utc_iso8601(self):
        stamp = self.manifest["built_at"]
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

    def test_every_hash_matches_the_zip_content(self):
        """manifest 存在的唯一理由是让用户能校验下载完整性 —— 它必须是对的。

        包很小（几十个文件、几百 KB），所以全查，不抽样。
        """
        with zipfile.ZipFile(self.zip_path) as archive:
            for entry in self.manifest["files"]:
                data = archive.read(f"{TOP}/{entry['path']}")
                self.assertEqual(len(data), entry["bytes"], entry["path"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"], entry["path"])

    def test_manifest_covers_every_packaged_file(self):
        """反过来也要成立：包里不能有 manifest 没列的文件。"""
        listed = {entry["path"] for entry in self.manifest["files"]}
        actual = {name[len(TOP) + 1 :] for name in self.names}
        self.assertEqual(actual - listed, {"release-manifest.json"})
        self.assertEqual(listed - actual, set())


class TestReproducibleBuild(unittest.TestCase):
    def test_two_builds_produce_the_same_manifest(self):
        """同一份源码构建两次，每个文件的 sha256 必须一致。

        这条是给「用户在 release 页面校验哈希」兜底的：如果构建本身不稳定，
        哈希就没有意义。built_at 是唯一允许变动的字段。
        """
        manifests = []
        tmp = tempfile.TemporaryDirectory(prefix="biaochi-repro-test-")
        self.addCleanup(tmp.cleanup)
        for index in range(2):
            out_dir = Path(tmp.name) / f"dist{index}"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(build.main(["--out", str(out_dir)]), 0)
            zip_path = out_dir / f"{TOP}-{build.default_platform()}.zip"
            with zipfile.ZipFile(zip_path) as archive:
                manifests.append(json.loads(archive.read(f"{TOP}/release-manifest.json")))

        first, second = manifests
        self.assertEqual(first["files"], second["files"])
        self.assertEqual(first["file_count"], second["file_count"])
        self.assertEqual(first["total_bytes"], second["total_bytes"])
        self.assertEqual(
            {k: v for k, v in first.items() if k != "built_at"},
            {k: v for k, v in second.items() if k != "built_at"},
        )


class TestLineEndings(BuildFixture):
    """.bat / .ps1 必须是 CRLF，其余文本文件统一 LF。

    为什么较真：cmd 对 LF 的 .bat 容忍度很差，而 PowerShell 5.1 读**没有 BOM**
    的 UTF-8 .ps1 会按系统 ANSI 解码 —— 中文提示全变乱码，用户看到的就是天书。
    这两条都是真踩过的坑，所以用测试钉住。
    """

    def test_bat_is_crlf_without_bom(self):
        data = self.read("一键启动.bat")
        self.assertFalse(data.startswith(b"\xef\xbb\xbf"), "cmd 会把 BOM 当成第一条命令")
        self.assertIn(b"\r\n", data)
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))

    def test_launcher_ps1_is_crlf_with_bom(self):
        data = self.read("scripts/launch.ps1")
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"), "PS 5.1 需要 BOM 才能正确读中文")
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))

    def test_run_ps1_is_normalized_to_crlf(self):
        """源码树里这个文件是 LF（历史原因），打包时必须规范化成 CRLF。"""
        data = self.read("run.ps1")
        self.assertNotIn(b"\n", data.replace(b"\r\n", b""))

    def test_every_ps1_is_crlf_and_has_bom_when_needed(self):
        """规则对所有 .ps1 生效，不只是启动器 —— 仓库里每个都得能显示中文。

        回归：`run.ps1` 和 `scripts/setup_vendor.ps1` 都带中文却没有 BOM，
        PS 5.1 下会打印成乱码。现在打包这一层会自动补，源码树里也补齐了。
        """
        ps1 = [name for name in self.names if name.endswith(".ps1")]
        self.assertTrue(ps1, "包里一个 .ps1 都没有？")
        for name in ps1:
            with self.subTest(file=name):
                data = self.read(name[len(TOP) + 1 :])
                self.assertNotIn(b"\n", data.replace(b"\r\n", b""), f"{name} 不是 CRLF")
                if any(byte > 127 for byte in data):
                    self.assertTrue(
                        data.startswith(b"\xef\xbb\xbf"),
                        f"{name} 有非 ASCII 却没有 BOM，PS 5.1 会乱码",
                    )

    def test_every_bat_has_no_bom(self):
        """BOM 在 .bat 里会被 cmd 当成第一条命令执行。"""
        for name in [n for n in self.names if n.endswith((".bat", ".cmd"))]:
            with self.subTest(file=name):
                self.assertFalse(self.read(name[len(TOP) + 1 :]).startswith(b"\xef\xbb\xbf"))

    def test_start_sh_keeps_lf(self):
        data = self.read("start.sh")
        self.assertNotIn(b"\r", data, "CRLF 的 shell 脚本在 Linux 上会报 bad interpreter")

    def test_python_files_keep_lf(self):
        data = self.read("biaochi/engine.py")
        self.assertNotIn(b"\r", data)


class TestCliContract(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="biaochi-cli-test-")
        self.addCleanup(self.tmp.cleanup)
        self.out_dir = Path(self.tmp.name) / "dist"

    def run_main(self, argv: list[str]) -> tuple[int, str]:
        # stderr 也吞掉：--expect-tag 失败时脚本会往 stderr 打中文说明，
        # 那是给 CI 日志看的，不该混进测试输出里。
        buffer = io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(buffer):
            code = build.main(argv)
        return code, buffer.getvalue()

    def test_expect_tag_accepts_matching_tag(self):
        for tag in (f"v{VERSION}", VERSION, f"refs/tags/v{VERSION}"):
            code, _ = self.run_main(["--out", str(self.out_dir), "--expect-tag", tag])
            self.assertEqual(code, 0, tag)

    def test_expect_tag_rejects_mismatch(self):
        """tag 和 version.py 不一致时必须失败 —— 这是 CI 里唯一的防线。"""
        for tag in ("v0.0.1", "v4.1.0-rc1", "release-4"):
            with self.assertRaises(SystemExit) as caught:
                self.run_main(["--out", str(self.out_dir), "--expect-tag", tag])
            self.assertEqual(caught.exception.code, 2, tag)

    def test_print_version(self):
        code, output = self.run_main(["--print-version"])
        self.assertEqual(code, 0)
        self.assertEqual(output.strip(), VERSION)

    def test_list_writes_nothing(self):
        code, output = self.run_main(["--list", "--out", str(self.out_dir)])
        self.assertEqual(code, 0)
        self.assertIn("biaochi/engine.py", output)
        self.assertFalse(self.out_dir.exists(), "--list 不该写任何东西")

    def test_no_zip_writes_a_tree(self):
        code, _ = self.run_main(["--out", str(self.out_dir), "--no-zip"])
        self.assertEqual(code, 0)
        self.assertTrue((self.out_dir / TOP / "biaochi" / "engine.py").is_file())
        self.assertTrue((self.out_dir / TOP / "release-manifest.json").is_file())
        self.assertFalse(list(self.out_dir.glob("*.zip")))

    def test_platform_is_part_of_the_zip_name(self):
        code, _ = self.run_main(["--out", str(self.out_dir), "--platform", "linux"])
        self.assertEqual(code, 0)
        self.assertTrue((self.out_dir / f"{TOP}-linux.zip").is_file())

    def test_custom_name_and_version(self):
        code, _ = self.run_main(
            ["--out", str(self.out_dir), "--name", "demo", "--version", "9.9.9"]
        )
        self.assertEqual(code, 0)
        self.assertTrue((self.out_dir / f"demo-9.9.9-{build.default_platform()}.zip").is_file())


class TestPackagedTreeIsUsable(BuildFixture):
    """解压出来的包必须能 import。

    这条是 vendor 子集够不够的**唯一**真凭实据：engine.py 只 import
    semif_phase1.core / .direct，只要子集挑漏了一个模块，这里就会炸。
    用子进程跑，免得污染当前进程的 sys.modules；不加载模型，所以还是秒级。
    """

    def test_packaged_engine_imports(self):
        target = Path(self.tmp.name) / "extracted"
        with zipfile.ZipFile(self.zip_path) as archive:
            archive.extractall(target)
        package = target / TOP

        code = (
            "import biaochi.engine as engine, biaochi.server, biaochi.profiles\n"
            "import semif_phase1.core, semif_phase1.direct\n"
            "print(engine.__file__)\n"
            "print(semif_phase1.core.__file__)\n"
            "print(''.join(label['id'] for label in engine.MEME_LABELS))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(package),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.strip().splitlines()
        # 确认真的 import 的是解压出来的那份，而不是仓库里的那份。
        self.assertTrue(Path(lines[0]).is_relative_to(package), lines[0])
        self.assertTrue(Path(lines[1]).is_relative_to(package), lines[1])
        self.assertEqual(lines[2], "典孝急乐蚌批赢麻")

    def test_packaged_tests_can_run(self):
        """包里带了 tests/，那些模块就得能 import 进来。

        为什么只 import 不执行：这是**嵌套**场景 —— 从解压出来的包里跑
        tests/test_release.py，它又会去解压、又去跑一遍，无限递归。
        而且跑整套还会被别的模块的临时状态牵连，这里要验证的只是
        「tests/ 连同它依赖的 scripts/ 都完整地在包里，import 不炸」。
        """
        target = Path(self.tmp.name) / "extracted-for-tests"
        with zipfile.ZipFile(self.zip_path) as archive:
            archive.extractall(target)
        package = target / TOP
        code = (
            "import importlib, pathlib\n"
            "modules = sorted(p.stem for p in pathlib.Path('tests').glob('test_*.py'))\n"
            "for name in modules:\n"
            "    importlib.import_module('tests.' + name)\n"
            "print(len(modules))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(package),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreaterEqual(int(result.stdout.strip()), len(
            [p for p in (PROJECT_ROOT / "tests").glob("test_*.py")]
        ))


class TestHelpers(unittest.TestCase):
    """规则用到的几个纯函数，单独钉一下边界。"""

    def test_normalize_bytes_bat_is_crlf(self):
        self.assertEqual(build.normalize_bytes("a.bat", b"x\ny\n"), b"x\r\ny\r\n")
        self.assertEqual(build.normalize_bytes("a.bat", b"x\r\ny\r\n"), b"x\r\ny\r\n")

    def test_normalize_bytes_python_is_lf(self):
        self.assertEqual(build.normalize_bytes("a.py", b"x\r\ny\r\n"), b"x\ny\n")

    def test_normalize_bytes_leaves_binary_alone(self):
        """顶着一个文本后缀的二进制文件不能被改坏。"""
        payload = b"\x89PNG\r\n\x1a\n\x00\x01"
        self.assertEqual(build.normalize_bytes("weird.md", payload), payload)

    def test_version_matches_source_of_truth(self):
        version, schema = build.read_version()
        self.assertEqual(version, VERSION)
        self.assertIsInstance(schema, int)

    def test_default_platform_is_known(self):
        self.assertIn(build.default_platform(), {"win64", "linux", "macos"})

    def test_excluded_dir_list_covers_the_dangerous_ones(self):
        for name in (".venv", ".git", "models", "__pycache__", "dist", ".github"):
            self.assertIn(name, build.EXCLUDED_DIRS)

    def test_required_files_all_exist_in_the_tree(self):
        """构建脚本里的必需清单不能指向不存在的文件（否则包永远构建不出来）。"""
        for relative in build.REQUIRED_FILES:
            if relative == "VERSION":
                continue  # 生成的文件
            self.assertTrue((PROJECT_ROOT / relative).is_file(), relative)


if __name__ == "__main__":
    unittest.main()
