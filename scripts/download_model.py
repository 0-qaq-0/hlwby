"""把基座模型拉到项目内的 models/ 目录。

默认下载 Qwen3.5-2B（留出集实测 87%，中位约 90 ms）。
可以按名字选别的基座：

    python scripts/download_model.py --model qwen3.5-2b     # 4.3 GB，默认
    python scripts/download_model.py --model qwen3-0.6b     # 1.4 GB，更快更弱
    python scripts/download_model.py --model qwen3.5-4b     # 8.7 GB，更准更重
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from biaochi.engine import DEFAULT_MODEL_DIR, MODEL_CHOICES  # noqa: E402

ALLOW_PATTERNS = ["*.json", "*.safetensors", "*.txt", "*.model"]


def main() -> None:
    parser = argparse.ArgumentParser(description="下载基座模型到项目内")
    parser.add_argument(
        "--model",
        choices=sorted(MODEL_CHOICES),
        default="qwen3.5-2b",
        help="要下载哪个基座",
    )
    parser.add_argument("--repo-id", default=None, help="直接指定 HF repo（覆盖 --model）")
    parser.add_argument("--revision", default=None)
    parser.add_argument("--target", type=Path, default=None)
    args = parser.parse_args()

    if args.repo_id:
        repo_id = args.repo_id
        revision = args.revision
        target = args.target or DEFAULT_MODEL_DIR
    else:
        name, revision = MODEL_CHOICES[args.model]
        repo_id = f"Qwen/{name}"
        target = args.target or PROJECT_ROOT / "models" / name

    from huggingface_hub import snapshot_download

    print(f"下载 {repo_id}@{str(revision)[:12]} -> {target}")
    path = snapshot_download(
        repo_id=repo_id,
        revision=revision,
        local_dir=str(target),
        allow_patterns=ALLOW_PATTERNS,
    )
    size = sum(f.stat().st_size for f in Path(path).rglob("*") if f.is_file())
    print(f"完成：{path}（{size / 1024**3:.2f} GB）")


if __name__ == "__main__":
    main()
