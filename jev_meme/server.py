"""八艺判定页面 + JSON API。

只用标准库，不额外引依赖：模型在启动时加载一次并常驻显存/内存，
之后每个请求就是一次前向传播。
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "web"

from .engine import (
    DEFAULT_MODEL_DIR,
    DEFAULT_PERMUTATIONS,
    DEFAULT_REVISION,
    MODEL_CHOICES,
    MemeJev,
    pick_device,
)
from .labels import CRITERION, EXAMPLES, LABELS_BY_ID, MEME_LABELS

MAX_BODY_BYTES = 256 * 1024
MAX_TEXT_CHARS = 20000

#: 请求体被拒时，最多再读掉多少字节。
#:
#: 为什么要在报错前读：客户端是按 `Content-Length` 一次性写过来的，
#: 服务端不读就回响应，客户端可能还在写 —— Windows 上这会变成
#: `ConnectionAbortedError (WinError 10053)`，测试会随机红。
#: 有封顶是为了不让一个巨大的 `Content-Length` 把连接拖住。
MAX_DRAIN_BYTES = 8 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    server_version = "MemeJev/3.0"
    engine: MemeJev  # 由 serve() 注入

    # -------------------------------------------------------------- 工具

    def _drain(self, count: int) -> None:
        """把已声明但决定不处理的请求体读掉，避免客户端写一半被 RST。"""
        remaining = count
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"ok": False, "error": message})

    def log_message(self, fmt: str, *args) -> None:  # 安静一点
        sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")

    # -------------------------------------------------------------- 路由

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]

        if path == "/api/health":
            self._json(
                200,
                {
                    "ok": True,
                    "loaded": self.engine.loaded,
                    "device": self.engine.metadata.get("device", ""),
                    "dtype": self.engine.metadata.get("dtype", ""),
                    "model": self.engine.metadata.get("source", ""),
                    "model_name": Path(self.engine.metadata.get("source", "")).name,
                    "load_seconds": self.engine.load_seconds,
                    "default_permutations": DEFAULT_PERMUTATIONS,
                    # 锚点（prompt）版本。改了 labels.py 的措辞就该改它 ——
                    # 不然「这个数字是哪版锚点测的」就说不清了。
                    "prompt_version": self.engine.metadata.get("prompt_version", ""),
                    "labels": [label["id"] for label in MEME_LABELS],
                },
            )
            return

        if path == "/api/labels":
            self._json(
                200,
                {
                    "ok": True,
                    "criterion": CRITERION,
                    "labels": MEME_LABELS,
                    "examples": EXAMPLES,
                },
            )
            return

        if path in ("/", "/index.html"):
            self._serve_file(WEB_DIR / "index.html")
            return

        # 其余按静态文件处理，限制在 web/ 目录内。
        candidate = (WEB_DIR / path.lstrip("/")).resolve()
        if WEB_DIR.resolve() in candidate.parents and candidate.is_file():
            self._serve_file(candidate)
            return

        self._error(404, f"没有这个路径：{path}")

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    def _serve_file(self, path: Path) -> None:
        if not path.is_file():
            self._error(404, f"缺少文件：{path}")
            return
        content_type, _ = mimetypes.guess_type(str(path))
        if path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif path.suffix in (".js", ".css"):
            content_type = f"{content_type or 'text/plain'}; charset=utf-8"
        self._send(200, path.read_bytes(), content_type or "application/octet-stream")

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path != "/api/decide":
            self._error(404, f"没有这个接口：{path}")
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._error(400, "Content-Length 不合法")
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self._drain(min(length, MAX_DRAIN_BYTES))
            self._error(400, f"请求体长度必须在 1 到 {MAX_BODY_BYTES} 字节之间")
            return

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            self._error(400, f"请求体不是合法 JSON：{error}")
            return
        if not isinstance(payload, dict):
            self._error(400, "请求体必须是一个 JSON 对象")
            return

        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            self._error(400, "字段 text 必须是非空字符串")
            return
        if len(text) > MAX_TEXT_CHARS:
            self._error(400, f"文本太长，最多 {MAX_TEXT_CHARS} 字")
            return

        permutations = payload.get("permutations", DEFAULT_PERMUTATIONS)
        if not isinstance(permutations, int) or isinstance(permutations, bool):
            self._error(400, "permutations 必须是整数")
            return
        if not 1 <= permutations <= 16:
            self._error(400, "permutations 必须在 1 到 16 之间")
            return

        profile = payload.get("profile", None)
        if profile not in (None, "bayi"):
            self._error(400, "现在只有「八艺」一套词表，不需要 profile 参数")
            return

        started = time.perf_counter()
        try:
            result = self.engine.decide(text, permutations=permutations)
        except ValueError as error:
            self._error(400, str(error))
            return
        except Exception as error:  # noqa: BLE001 - 兜底，避免整个服务挂掉
            traceback.print_exc()
            self._error(500, f"判定失败：{error}")
            return

        result["ok"] = True
        result["server_ms"] = round((time.perf_counter() - started) * 1000, 2)
        self._json(200, result)


def serve(
    host: str,
    port: int,
    model_dir: Path,
    revision: str,
    device: str,
) -> None:
    print(f"[meme-jev] 目标设备: {pick_device(device)}")
    print(f"[meme-jev] 加载模型: {model_dir}")
    engine = MemeJev(model_dir=model_dir, revision=revision, device=device)
    engine.load()
    print(
        f"[meme-jev] 模型就绪，用时 {engine.load_seconds:.1f}s "
        f"({engine.metadata.get('device')}, {engine.metadata.get('dtype')})"
    )
    print(f"[meme-jev] 词表: {''.join(label['id'] for label in MEME_LABELS)}")
    probe = engine.decide("预热文本")
    print(f"[meme-jev] 一次判定约 {probe['forward_ms']:.0f} ms（{probe['permutations']} 排列）")

    Handler.engine = engine
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    print(f"[meme-jev] 页面地址: http://{host}:{port}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[meme-jev] 收到中断，正在退出")
    finally:
        httpd.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="八艺 —— 这条评论该回哪个字")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8770)
    parser.add_argument(
        "--model",
        choices=sorted(MODEL_CHOICES),
        default=None,
        help="快捷选择基座（覆盖 --model-dir / --revision）",
    )
    parser.add_argument("--model-dir", type=Path, default=DEFAULT_MODEL_DIR)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    args = parser.parse_args()

    model_dir, revision = args.model_dir, args.revision
    if args.model:
        name, revision = MODEL_CHOICES[args.model]
        model_dir = PROJECT_ROOT / "models" / name

    serve(args.host, args.port, model_dir, revision, args.device)


if __name__ == "__main__":
    main()
