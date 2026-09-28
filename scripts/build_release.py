#!/usr/bin/env python3
"""本地构建「八艺」的 release 包（zip）。

为什么要有这个脚本：仓库里躺着 30MB 的上游评测资产和 4.3GB 的模型权重，
直接 `git archive` 出来的东西用户既下不动也用不上。这里用**一份集中的
包含 / 排除规则**把包裁到只剩运行时需要的东西，再生成 `release-manifest.json`
让用户能校验下载下来的包没坏、没缺文件。

两个硬要求（都踩过坑）：

1. **纯标准库**。CI 上不装 torch / transformers 也要能构建 —— 它们只是运行
   时依赖。所以这里刻意不 import ``jev_meme``（它的 ``__init__`` 会牵连一堆
   东西），版本号用正则从 ``version.py`` 里抠出来。
2. **可重复**。同一份源码构建两次，manifest 里每个文件的 sha256 必须一模一样。
   为此：文本文件打包时统一换行符（不然 Windows 检出的 CRLF 和 Linux 检出的
   LF 会给出两份不同的哈希）、zip 内时间戳固定、manifest **不把自己**算进去
   （否则哈希自指，永远不稳定）。

用法：

    python scripts/build_release.py --out dist        # 打 zip
    python scripts/build_release.py --list            # 只看包里有什么
    python scripts/build_release.py --expect-tag v4.0.0   # CI 里校验 tag 与版本号
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform as platform_module
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- 版本号

#: 从源码里抠版本号，而不是 import —— 构建脚本不该依赖运行时依赖。
_VERSION_RE = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
_SCHEMA_RE = re.compile(r"^SCHEMA_VERSION\s*=\s*(\d+)", re.MULTILINE)

# ------------------------------------------------------------ 包含规则

#: 要收进包的顶层目录（相对仓库根）。
#: ``vendor`` 也在里面，但只会收下必需子集 —— 过滤在 _file_is_excluded 里。
PACKAGE_ROOTS = ("jev_meme", "web", "scripts", "tests", "data", "docs", "vendor")

#: 仓库根下要单独收的文件。
#: ``.gitignore`` / ``.gitattributes`` 也带上：体积可忽略，但用户把解压出来的
#: 目录 `git init` 之后，换行符规则和忽略规则跟原仓库一致。
ROOT_FILES = (
    "requirements.txt",
    "LICENSE",
    "README.md",
    "README-启动.md",
    "一键启动.bat",
    "start.sh",
    "run.ps1",
    ".gitignore",
    ".gitattributes",
)

#: 缺了就直接构建失败 —— 这些是「包能用」的底线，静默少一个文件比报错更糟。
REQUIRED_FILES = (
    "jev_meme/__init__.py",
    "jev_meme/engine.py",
    "jev_meme/server.py",
    "jev_meme/version.py",
    "jev_meme/labels.py",
    "web/index.html",
    "scripts/build_release.py",
    "scripts/download_model.py",
    "scripts/launch.ps1",
    "tests/__init__.py",
    "data/eval_clean.jsonl",
    "data/eval_overlap.jsonl",
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
    "一键启动.bat",
    "start.sh",
    "run.ps1",
    "VERSION",
)

# ------------------------------------------------------------ 排除规则
#
# 所有排除规则都集中在这一段，别处不再写第二套判断 —— 否则「为什么这个文件
# 在包里 / 不在包里」会变成考古题。

#: 任何层级命中就整棵剪掉的目录名。
#:   * ``.venv``/``venv``/``env`` —— 用户自己的虚拟环境，几百 MB 且不可移植
#:   * ``models`` —— 权重，默认不进包（见 --with-model），4.3GB
#:   * ``.git`` —— 仓库元数据
#:   * ``.cache`` —— scripts/page_check.py 之类写出来的临时缓存
#:   * ``__pycache__``/``.pytest_cache``/``.mypy_cache``/``.ruff_cache`` —— 构建垃圾
#:   * ``dist``/``build`` —— 上一次的构建产物（默认输出目录就叫 dist，
#:     不剪掉的话第二次构建会把第一次的 zip 打进包里）
#:   * ``.github`` —— CI 配置，对「拿到包只想跑起来」的用户没有任何用，
#:     反而容易让人以为要在解压目录里发 release
EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "env",
        "models",
        "dist",
        "build",
        ".cache",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
        "node_modules",
        "__pycache__",
        ".github",
    }
)

#: 文件后缀黑名单：字节码 / 临时文件。
EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo"})

#: 文件名黑名单：系统垃圾和本机配置。
EXCLUDED_NAMES = frozenset({".DS_Store", "Thumbs.db", "desktop.ini", ".env"})

#: **用户数据**不进包。
#:
#: ``data/profiles/*.json`` 是用户自己在页面上存下来的判断类型，``data/eval_results/``
#: 是用户自己跑评测的产物 —— 那是别人的数据，混进发行包既没用又可能泄露隐私。
#: 但目录本身要留一个 ``.gitkeep`` 占位，不然服务启动后第一次保存类型才会建目录。
USER_DATA_DIRS = ("data/profiles", "data/eval_results")

#: 占位文件名。留它是因为 git / zip 都不记录空目录。
PLACEHOLDER_NAME = ".gitkeep"

# ------------------------------------------------------ vendor 必需子集
#
# 上游 SemIf-OpenJev 整个仓库都在源码树里（含 ~30MB 的 results/benchmarks/demo
# 资产），但运行时**只 import `semif_phase1.core` 和 `semif_phase1.direct`**
# （见 jev_meme/engine.py）。所以包里只带这几个 .py + 许可 + 说明 + pyproject，
# 保证 MIT 归属完整、又不用让用户下 30MB 用不上的评测数据。

VENDOR_ROOT = "vendor/SemIf-OpenJev"

#: 除了下面的 .py，还要原样带上的文件（许可与出处）。
VENDOR_FILES = ("LICENSE", "README.md", "pyproject.toml")

#: 引擎真正会 import 的包目录。整个目录的 .py 都带上 —— 只挑 core/direct
#: 的话，哪天 engine.py 多 import 一个模块就会在用户机器上炸，而带上整个包
#: 只多几十 KB。
VENDOR_PY_DIR = "src/semif_phase1"

#: 上游仓库里这些目录一个字节都不进包（剪掉之后遍历也快得多）。
VENDOR_EXCLUDED_DIRS = frozenset(
    {
        "results",
        "benchmarks",
        "webgpu-demo",
        "demo",
        "assets",
        "exl3-bridge",
        "manifests",
        "tests",
        "docs",
        "examples",
    }
)

# ------------------------------------------------------------ 换行符

#: 这几个后缀在包里必须是 CRLF：Windows 的 cmd / PowerShell 对 LF 的 .bat
#: 容忍度很差（尤其带中文和 `chcp` 的时候），仓库的 .gitattributes 也是这么定的。
CRLF_SUFFIXES = frozenset({".bat", ".cmd", ".ps1"})

#: UTF-8 BOM。只给带非 ASCII 的 .ps1 补 —— 见 normalize_bytes。
UTF8_BOM = b"\xef\xbb\xbf"

#: 其余文本文件统一成 LF。为什么不保持原样：Windows 上 `core.autocrlf=true`
#: 检出的工作区是 CRLF、Linux 上是 LF，不统一的话同一次 release 在
#: windows-latest / ubuntu-latest 上构建出来的两个 zip 内容不一样，
#: manifest 里的哈希也就对不上，用户校验时会以为包坏了。
LF_SUFFIXES = frozenset(
    {
        ".py",
        ".pyi",
        ".md",
        ".txt",
        ".json",
        ".jsonl",
        ".html",
        ".css",
        ".js",
        ".mjs",
        ".toml",
        ".yml",
        ".yaml",
        ".sh",
        ".cfg",
        ".ini",
        ".csv",
        ".tsv",
        ".xml",
        ".svg",
    }
)

#: 没有后缀但确实是文本的文件。
LF_NAMES = frozenset({"VERSION", "LICENSE", PLACEHOLDER_NAME, ".gitignore", ".gitattributes"})

#: zip 内固定时间戳（DOS 时间能表示的最小值）。
#: 不固定的话每次构建的 zip 字节都不同，「可重复构建」就无从谈起。
#: 想改成真实时间就设环境变量 SOURCE_DATE_EPOCH（可重复构建的通用约定）。
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)

MANIFEST_NAME = "release-manifest.json"
VERSION_NAME = "VERSION"


# ================================================================ 小工具


def read_version() -> tuple[str, int]:
    """从 ``jev_meme/version.py`` 抠出 (__version__, SCHEMA_VERSION)。"""
    text = (PROJECT_ROOT / "jev_meme" / "version.py").read_text(encoding="utf-8")
    version = _VERSION_RE.search(text)
    schema = _SCHEMA_RE.search(text)
    if not version or not schema:
        raise SystemExit("读不出 jev_meme/version.py 里的 __version__ / SCHEMA_VERSION")
    return version.group(1), int(schema.group(1))


def default_platform() -> str:
    """按当前系统给一个平台标签（只影响 zip 文件名，不影响内容）。"""
    if sys.platform.startswith("win"):
        return "win64"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def normalize_bytes(name: str, data: bytes) -> bytes:
    """按后缀统一换行符，让包内容与检出平台无关。

    带 NUL 的一律当二进制原样放行 —— 万一某个二进制文件顶着文本后缀，
    统一换行符会把它改坏。
    """
    if b"\x00" in data:
        return data
    suffix = Path(name).suffix.lower()
    if suffix in CRLF_SUFFIXES:
        data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        # PowerShell 5.1（Windows 自带那个）读**没有 BOM** 的脚本会按 ANSI 解码，
        # 于是脚本里的中文全是乱码 —— 而我们的启动器通篇是中文。
        # 所以在打包这一层补上，不指望每个写 .ps1 的人都记得。
        # 注意 .bat/.cmd **绝对不能**有 BOM：cmd 会把 BOM 当成第一条命令。
        if suffix == ".ps1" and not data.startswith(UTF8_BOM) and any(byte > 127 for byte in data):
            data = UTF8_BOM + data
        return data
    if suffix in LF_SUFFIXES or (suffix == "" and Path(name).name in LF_NAMES):
        return data.replace(b"\r\n", b"\n")
    return data


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def human_bytes(count: int) -> str:
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.2f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.2f} GB"


# ============================================================ 收集文件


def _dir_is_excluded(name: str, rel_dir: str, abs_dir: Path, out_abs: str, with_model: bool) -> bool:
    """这个目录要不要整棵剪掉。``rel_dir`` 是相对仓库根的 posix 路径（根为 ""）。"""
    if name in EXCLUDED_DIRS:
        # models/ 例外：--with-model 时是唯一需要收进来的大目录。
        if name == "models" and with_model:
            return False
        return True
    if rel_dir.startswith(VENDOR_ROOT) and name in VENDOR_EXCLUDED_DIRS:
        return True
    # 输出目录本身要剪掉：--out 可能就指在仓库里，不剪的话第二次构建
    # 会把上一次的 zip / 解压目录收进包。
    return os.path.normcase(str(abs_dir)) == out_abs


def _file_is_excluded(name: str, rel: str) -> bool:
    if name in EXCLUDED_NAMES or Path(name).suffix.lower() in EXCLUDED_SUFFIXES:
        return True
    # 用户数据只留 .gitkeep 占位。
    if rel.startswith(USER_DATA_DIRS):
        return name != PLACEHOLDER_NAME
    # vendor 只带必需子集。
    if rel.startswith(VENDOR_ROOT + "/"):
        inner = rel[len(VENDOR_ROOT) + 1 :]
        if inner in VENDOR_FILES:
            return False
        return not (inner.startswith(VENDOR_PY_DIR + "/") and inner.endswith(".py"))
    return False


def collect_files(out_dir: Path, with_model: bool) -> list[tuple[Path, str]]:
    """遍历仓库，返回 ``[(绝对路径, 包内相对路径)]``，按包内路径排序。"""
    out_abs = os.path.normcase(str(out_dir.resolve()))
    found: list[tuple[Path, str]] = []

    def walk(abs_dir: Path, rel_dir: str) -> None:
        try:
            entries = sorted(os.scandir(abs_dir), key=lambda e: e.name)
        except OSError:
            return
        for entry in entries:
            rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
            if entry.is_dir(follow_symlinks=False):
                if not _dir_is_excluded(entry.name, rel, Path(entry.path), out_abs, with_model):
                    walk(Path(entry.path), rel)
            elif entry.is_file(follow_symlinks=False) and not _file_is_excluded(entry.name, rel):
                found.append((Path(entry.path), rel))

    for root_name in PACKAGE_ROOTS:
        root_path = PROJECT_ROOT / root_name
        if root_path.is_dir():
            walk(root_path, root_name)
    # models/ 平时不在 PACKAGE_ROOTS 里（4.3GB），只有 --with-model 时才收。
    if with_model and (PROJECT_ROOT / "models").is_dir():
        walk(PROJECT_ROOT / "models", "models")
    for file_name in ROOT_FILES:
        path = PROJECT_ROOT / file_name
        if path.is_file():
            found.append((path, file_name))

    return sorted(found, key=lambda item: item[1])


def build_payload(files: list[tuple[Path, str]], version: str, schema: int,
                  name: str, platform_tag: str, with_model: bool) -> dict[str, bytes]:
    """把文件读成 ``{包内路径: 字节}``，并补上生成的文件（不含 manifest）。"""
    payload: dict[str, bytes] = {}
    for abs_path, rel in files:
        payload[rel] = normalize_bytes(rel, abs_path.read_bytes())

    # VERSION：内容是版本号，方便用户不打开任何文件就知道手里这包是哪版。
    payload[VERSION_NAME] = f"{version}\n".encode("utf-8")

    # 空目录占位：zip 不记录空目录，服务第一次保存判断类型时才会 mkdir，
    # 所以这里显式放一个 .gitkeep，用户解压出来就能看到目录该在哪。
    for dir_rel in USER_DATA_DIRS:
        placeholder = f"{dir_rel}/{PLACEHOLDER_NAME}"
        payload.setdefault(placeholder, b"")

    if with_model:
        total = sum(len(v) for k, v in payload.items() if k.startswith("models/"))
        print(f"[build] 警告：--with-model 把模型权重也打进了包（{human_bytes(total)}）。",
              file=sys.stderr)
        print("[build] 警告：GitHub Release 单个附件上限 2GB，超了传不上去；"
              "建议只在局域网 / 离线分发时用这个开关。", file=sys.stderr)
        # 打包时文件内容是整个读进内存的（要算 sha256、要写 zip），
        # 所以 --with-model 的内存占用跟包体积同量级。这句话是给
        # 「8GB 内存的机器打 4.3GB 的模型包然后被 OOM 杀掉」的人看的。
        print(f"[build] 警告：本次构建大约要占用 {human_bytes(total)} 内存，"
              "机器内存不够就分两次打（先不带权重，权重单独拷）。", file=sys.stderr)

    return payload


def make_manifest(payload: dict[str, bytes], *, name: str, version: str, schema: int,
                  platform_tag: str) -> dict:
    """生成 manifest。**不含自己** —— 自指会让哈希永远不稳定。"""
    entries = [
        {"path": path, "bytes": len(data), "sha256": sha256_of(data)}
        for path, data in sorted(payload.items())
    ]
    return {
        "name": name,
        "version": version,
        "schema": schema,
        "platform": platform_tag,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": platform_module.python_version(),
        "file_count": len(entries),
        "total_bytes": sum(entry["bytes"] for entry in entries),
        "files": entries,
    }


# ============================================================== 写产物


def _zip_datetime() -> tuple[int, int, int, int, int, int]:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch and epoch.isdigit():
        stamp = datetime.fromtimestamp(int(epoch), timezone.utc)
        return (stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute, stamp.second)
    return FIXED_ZIP_TIME


def write_zip(zip_path: Path, payload: dict[str, bytes], top: str) -> None:
    """写出 zip：顶层只有一个目录 ``top``，解压出来不会散落一地。"""
    stamp = _zip_datetime()
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel in sorted(payload):
            info = zipfile.ZipInfo(f"{top}/{rel}", date_time=stamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            # create_system=3 是 Unix，这样 unzip 会按 external_attr 还原权限位 ——
            # start.sh 需要可执行位，否则用户还得手动 chmod +x。
            info.create_system = 3
            mode = 0o755 if rel.endswith(".sh") else 0o644
            info.external_attr = mode << 16
            archive.writestr(info, payload[rel])


def write_tree(dir_path: Path, payload: dict[str, bytes]) -> None:
    """--no-zip：直接把包内容铺到目录里（调试 / 想自己再压一次时用）。"""
    for rel, data in sorted(payload.items()):
        target = dir_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


# ================================================================ 入口


def check_tag(tag: str, version: str) -> None:
    """校验 tag 与 version.py 一致。

    为什么要在构建期挡：release 页面上写着 v4.0.0、包里却是 3.9 的代码，
    是那种**发出去之后才发现**的错误。宁可让 CI 红。
    """
    cleaned = tag.strip()
    for prefix in ("refs/tags/", "refs/heads/"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
    cleaned = cleaned.lstrip("vV")
    if cleaned != version:
        print(
            f"[build] 失败：tag「{tag}」和 jev_meme/version.py 里的版本号「{version}」不一致。\n"
            f"[build] 请先把 version.py 的 __version__ 改成 {cleaned or '<版本号>'} 再打 tag，"
            f"或者把 tag 改成 v{version}。",
            file=sys.stderr,
        )
        raise SystemExit(2)
    print(f"[build] tag 校验通过：{tag} == {version}")


def main(argv: list[str] | None = None) -> int:
    source_version, schema = read_version()
    parser = argparse.ArgumentParser(
        description="构建「八艺」release 包（纯标准库，不需要装 torch）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "例：\n"
            "  python scripts/build_release.py --out dist\n"
            "  python scripts/build_release.py --list\n"
            "  python scripts/build_release.py --expect-tag v4.0.0\n"
        ),
    )
    parser.add_argument("--out", type=Path, default=Path("dist"), help="输出目录（默认 dist）")
    parser.add_argument("--version", default=source_version, help=f"覆盖版本号（默认 {source_version}）")
    parser.add_argument("--name", default="hlwby", help="包名前缀（默认 hlwby）")
    parser.add_argument(
        "--platform",
        default=default_platform(),
        choices=["win64", "linux", "macos"],
        help="平台标签，只影响 zip 文件名（默认按当前系统）",
    )
    parser.add_argument(
        "--with-model",
        action="store_true",
        help="把 models/ 里已有的权重也打进包（默认关；开了包会非常大）",
    )
    parser.add_argument("--zip", dest="make_zip", action="store_true", default=True,
                        help="打 zip（默认）")
    parser.add_argument("--no-zip", dest="make_zip", action="store_false",
                        help="不打 zip，只把包内容铺到 <out>/<name>-<version>/")
    parser.add_argument("--list", action="store_true", help="只列出会进包的文件，不写任何东西")
    parser.add_argument(
        "--print-version",
        action="store_true",
        help="只打印解析出来的版本号就退出（CI 里拼 tag 用）",
    )
    parser.add_argument(
        "--expect-tag",
        default=None,
        help="校验 tag（如 v4.0.0）与 version.py 一致，不一致直接失败；CI 用",
    )
    args = parser.parse_args(argv)

    # CI 里拼 tag 用：只吐版本号，别的什么都不做（好让 `$(...)` 干净地接住）。
    if args.print_version:
        print(args.version)
        return 0

    if args.expect_tag is not None:
        check_tag(args.expect_tag, args.version)

    out_dir = args.out if args.out.is_absolute() else (PROJECT_ROOT / args.out)
    top = f"{args.name}-{args.version}"

    print(f"[build] 版本 {args.version}（schema {schema}）/ 平台 {args.platform} / 包名 {args.name}")
    files = collect_files(out_dir, args.with_model)
    payload = build_payload(files, args.version, schema, args.name, args.platform, args.with_model)

    # manifest 最后算，且只算 payload（不含自己）。
    manifest = make_manifest(
        payload, name=args.name, version=args.version, schema=schema, platform_tag=args.platform
    )
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    payload[MANIFEST_NAME] = manifest_bytes

    total_bytes = sum(len(data) for data in payload.values())

    if args.list:
        for rel in sorted(payload):
            print(f"{len(payload[rel]):>10}  {rel}")
        print(f"[build] 共 {len(payload)} 个文件，{human_bytes(total_bytes)}"
              f"（含生成的 {VERSION_NAME}、{MANIFEST_NAME} 和占位 {PLACEHOLDER_NAME}）")
        return 0

    # 底线检查：必需文件一个都不能少。放到写产物之前，免得留下半个包。
    missing = [rel for rel in REQUIRED_FILES if rel not in payload]
    if missing:
        print("[build] 失败：包里缺少必需文件：", file=sys.stderr)
        for rel in missing:
            print(f"[build]   - {rel}", file=sys.stderr)
        return 1

    if args.make_zip:
        zip_path = out_dir / f"{top}-{args.platform}.zip"
        write_zip(zip_path, payload, top)
        zip_bytes = zip_path.read_bytes()
        print(f"[build] 文件 {len(payload)} 个，共 {human_bytes(total_bytes)}")
        print(f"[build] 已写出 {zip_path}（{human_bytes(len(zip_bytes))}）")
        print(f"[build] zip sha256: {sha256_of(zip_bytes)}")
        print(f"[build] 包内顶层目录：{top}/（解压不会散落一地）")
        print("[build] 给用户的提示：解压后双击「一键启动.bat」；"
              "Linux/macOS 跑 ./start.sh（首次会自动建环境、装依赖、下模型）")
    else:
        tree_path = out_dir / top
        write_tree(tree_path, payload)
        print(f"[build] 文件 {len(payload)} 个，共 {human_bytes(total_bytes)}")
        print(f"[build] 已铺出 {tree_path}")
        print(f"[build] manifest sha256: {sha256_of(manifest_bytes)}")

    print(f"[build] 校验用：{top}/{MANIFEST_NAME} 里每个文件的 sha256 都可与解压结果对照")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
