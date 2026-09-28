"""帮你挑一个判定页面 + JSON API。

只用标准库，不额外引依赖：模型在启动时加载一次并常驻显存/内存，
之后每个请求就是一次前向传播。

「判断类型」（profile）是可自定义的运行时数据，所以这里除了判定接口，
还有一整套类型管理接口：列 / 读 / 存 / 删 / 校验 / 导入 / 导出。
页面上的词表编辑器就是直接打这些接口 —— **没有第二套逻辑**。
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
from urllib.parse import parse_qs, unquote, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "web"

from .engine import (
    DEFAULT_MODEL_DIR,
    DEFAULT_PERMUTATIONS,
    DEFAULT_REVISION,
    MODEL_CHOICES,
    Tiaoyige,
    pick_device,
)
from .labels import CRITERION, EXAMPLES, LABELS_BY_ID, MEME_LABELS
from .profiles import (
    DEFAULT_PROFILE_ID,
    SLUG_RE,
    Profile,
    ProfileError,
    ProfileStore,
    errors_of,
    eval_result_path,
    profile_stats,
    validate,
)
from .version import __version__

MAX_BODY_BYTES = 256 * 1024
MAX_TEXT_CHARS = 20000

#: 请求体被拒时，最多再读掉多少字节。
#:
#: 为什么要在报错前读：客户端是按 `Content-Length` 一次性写过来的，
#: 服务端不读就回响应，客户端可能还在写 —— Windows 上这会变成
#: `ConnectionAbortedError (WinError 10053)`，测试会随机红。
#: 有封顶是为了不让一个巨大的 `Content-Length` 把连接拖住。
MAX_DRAIN_BYTES = 8 * 1024 * 1024


def dataset_summaries() -> list[dict]:
    """仓库里带了哪几套测试集、各多少条。

    页面上「评测」页要用它 —— 但**只报条数，不报准确率**：准确率只有一个出处
    （`data/eval_results/*.json`），页面不能自己算一份出来。
    """
    notes = {
        "eval_clean": "干净集：与锚点例句无字面重合，判断泛化能力以它为准",
        "eval_overlap": "对照集：装着已知和锚点撞过车的句子，数字不代表泛化能力",
    }
    out = []
    for name in ("eval_clean", "eval_overlap"):
        path = PROJECT_ROOT / "data" / f"{name}.jsonl"
        rows = 0
        if path.is_file():
            rows = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        out.append(
            {
                "name": name,
                "path": f"data/{name}.jsonl",
                "exists": path.is_file(),
                "rows": rows,
                "note": notes[name],
            }
        )
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = f"Tiaoyige/{__version__}"
    engine: Tiaoyige  # 由 serve() 注入
    store: ProfileStore = ProfileStore()  # 测试可以直接换掉

    # -------------------------------------------------------------- 工具

    def _drain(self, count: int) -> None:
        """把已声明但决定不处理的请求体读掉，避免客户端写一半被 RST。"""
        remaining = count
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: dict, extra: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra)

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"ok": False, "error": message})

    def _read_json(self, allow_empty: bool = False) -> tuple[dict | None, str | None]:
        """读一个 JSON 对象请求体。返回 ``(payload, error)``，两者必有一个是 None。"""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return None, "Content-Length 不合法"
        if length <= 0:
            if allow_empty:
                return {}, None
            return None, "请求体长度必须在 1 到 %d 字节之间" % MAX_BODY_BYTES
        if length > MAX_BODY_BYTES:
            self._drain(min(length, MAX_DRAIN_BYTES))
            return None, f"请求体长度必须在 1 到 {MAX_BODY_BYTES} 字节之间"
        raw = self.rfile.read(length)
        if not raw and allow_empty:
            return {}, None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            return None, f"请求体不是合法 JSON：{error}"
        if not isinstance(payload, dict):
            return None, "请求体必须是一个 JSON 对象"
        return payload, None

    @staticmethod
    def _split(path: str) -> tuple[str, dict[str, list[str]]]:
        parsed = urlparse(path)
        return parsed.path, parse_qs(parsed.query)

    def log_message(self, fmt: str, *args) -> None:  # 安静一点
        sys.stderr.write(f"[{self.log_date_time_string()}] {fmt % args}\n")

    # -------------------------------------------------------------- 路由

    def do_GET(self) -> None:  # noqa: N802
        path, query = self._split(self.path)

        if path == "/api/health":
            self._json(200, self._health_payload())
            return

        if path == "/api/profiles":
            profiles = self.store.list()
            self._json(
                200,
                {
                    "ok": True,
                    "default": DEFAULT_PROFILE_ID,
                    "profiles": [profile.to_summary() for profile in profiles],
                },
            )
            return

        if path.startswith("/api/profiles/"):
            rest = unquote(path[len("/api/profiles/") :])
            if rest.endswith("/export"):
                self._export_profile(rest[: -len("/export")])
                return
            self._get_profile(rest)
            return

        if path == "/api/labels":
            # 兼容老接口：等价于「八艺」这一套。
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

        if path == "/api/eval":
            profile_id = (query.get("profile") or [DEFAULT_PROFILE_ID])[0]
            # id 会拼进文件名，所以这里先挡一道 —— 见 eval_result_path 的注释。
            if not SLUG_RE.match(profile_id):
                self._error(400, f"判断类型 id 不合法：{profile_id!r}")
                return
            self._json(200, self._eval_payload(profile_id))
            return

        if path == "/api/datasets":
            self._json(200, {"ok": True, "datasets": dataset_summaries()})
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

    # -------------------------------------------------------------- GET 实现

    def _health_payload(self) -> dict:
        profiles = self.store.list()
        return {
            "ok": True,
            "version": __version__,
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
            "default_profile": DEFAULT_PROFILE_ID,
            "profiles": [profile.id for profile in profiles],
            "user_profile_dir": str(self.store.user_dir),
        }

    def _get_profile(self, profile_id: str) -> None:
        profile = self.store.get(profile_id)
        if profile is None:
            self._error(404, f"没有这个判断类型：{profile_id}")
            return
        issues = validate(profile)
        self._json(
            200,
            {
                "ok": True,
                "profile": profile.to_dict(),
                "issues": [issue.to_dict() for issue in issues],
                "stats": profile_stats(profile),
                "eval": self._eval_payload(profile_id),
            },
        )

    def _export_profile(self, profile_id: str) -> None:
        try:
            payload = self.store.export_dict(profile_id)
        except ProfileError as error:
            self._error(404, str(error))
            return
        body = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self._send(
            200,
            body,
            "application/json; charset=utf-8",
            {"Content-Disposition": f'attachment; filename="{profile_id}.json"'},
        )

    def _eval_payload(self, profile_id: str) -> dict:
        """某套类型的评测数字。

        为什么走接口而不是写在页面里：页面原来硬编码「24 条 96%」，
        测试集换成 52 条之后没人记得改，于是一个**已经作废的数字**
        在页面上挂了很久。数字只有一个出处，页面才不会过期。
        """
        path = eval_result_path(profile_id)
        if not path.is_file():
            return {
                "ok": True,
                "profile": profile_id,
                "available": False,
                "note": "这套判断类型还没跑过评测",
                "how": f"python scripts/evaluate.py --profile {profile_id} --write-result",
            }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            return {"ok": True, "profile": profile_id, "available": False, "note": f"结果文件读不出来：{error}"}
        return {"ok": True, "profile": profile_id, "available": True, **payload}

    def _serve_file(self, path: Path) -> None:
        if not path.is_file():
            self._error(404, f"缺少文件：{path}")
            return
        content_type, _ = mimetypes.guess_type(str(path))
        if path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        elif path.suffix in (".js", ".mjs", ".css", ".svg", ".json", ".webmanifest"):
            content_type = f"{content_type or 'text/plain'}; charset=utf-8"
        self._send(200, path.read_bytes(), content_type or "application/octet-stream")

    # -------------------------------------------------------------- POST

    def do_POST(self) -> None:  # noqa: N802
        path, _ = self._split(self.path)

        if path == "/api/decide":
            self._post_decide()
            return
        if path == "/api/profiles":
            self._post_profile_save()
            return
        if path == "/api/profiles/validate":
            self._post_profile_validate()
            return
        if path == "/api/profiles/delete":
            self._post_profile_delete()
            return
        if path == "/api/profiles/import":
            self._post_profile_import()
            return

        self._error(404, f"没有这个接口：{path}")

    # ------------------------------------------------------------- POST 实现

    def _post_decide(self) -> None:
        payload, error = self._read_json()
        if error:
            self._error(400, error)
            return
        assert payload is not None

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

        # 三种来源，优先级：内联词表 > profile id > 默认「八艺」。
        profile: Profile | None = None
        inline = payload.get("inline")
        if inline is not None:
            profile, error = self._inline_profile(inline)
            if error:
                self._error(400, error)
                return
        else:
            profile_id = payload.get("profile", DEFAULT_PROFILE_ID)
            if not isinstance(profile_id, str) or not profile_id:
                self._error(400, "profile 必须是字符串")
                return
            profile = self.store.get(profile_id)
            if profile is None:
                self._error(400, f"没有这个判断类型：{profile_id}")
                return

        started = time.perf_counter()
        try:
            result = self.engine.decide(text, permutations=permutations, profile=profile)
        except ValueError as error:
            self._error(400, str(error))
            return
        except Exception as error:  # noqa: BLE001 - 兜底，避免整个服务挂掉
            traceback.print_exc()
            self._error(500, f"判定失败：{error}")
            return

        result["ok"] = True
        result["profile"] = profile.id
        result["profile_name"] = profile.name
        result["server_ms"] = round((time.perf_counter() - started) * 1000, 2)
        self._json(200, result)

    @staticmethod
    def _inline_profile(inline: object) -> tuple[Profile | None, str | None]:
        """把页面上**还没保存**的词表拿来试判。

        编辑器要能「改一句锚点立刻看效果」，所以判定接口得吃得下未保存的数据。
        这里只挡会炸引擎的东西（数量、重复 id、空描述），经验性的检查交给
        ``/api/profiles/validate``，不拦试判 —— 试判本来就是用来试错的。
        """
        if not isinstance(inline, dict):
            return None, "inline 必须是一个对象"
        try:
            profile = Profile.from_dict({**inline, "id": inline.get("id") or "inline"})
        except ValueError as error:
            return None, str(error)
        if not profile.criterion:
            return None, "inline.criterion 不能为空"
        if not 2 <= len(profile.labels) <= 16:
            return None, f"inline.labels 必须是 2~16 个选项，现在 {len(profile.labels)} 个"
        ids = profile.label_ids
        if len(set(ids)) != len(ids):
            return None, "inline.labels 的选项 id 有重复"
        for label in profile.labels:
            if not label["description"]:
                return None, f"inline.labels 里「{label['id']}」没有锚点描述"
        return profile, None

    def _post_profile_validate(self) -> None:
        """只校验、不保存 —— 编辑器每敲几下就调它一次。"""
        payload, error = self._read_json()
        if error:
            self._error(400, error)
            return
        assert payload is not None
        raw = payload.get("profile", payload)
        try:
            profile = Profile.from_dict(raw)
        except ValueError as error:
            self._error(400, str(error))
            return
        issues = validate(profile)
        self._json(
            200,
            {
                "ok": True,
                "issues": [issue.to_dict() for issue in issues],
                "error_count": len(errors_of(issues)),
                "warning_count": len([i for i in issues if i.level == "warning"]),
                "stats": profile_stats(profile),
            },
        )

    def _post_profile_save(self) -> None:
        payload, error = self._read_json()
        if error:
            self._error(400, error)
            return
        assert payload is not None
        overwrite = bool(payload.get("overwrite", False))
        raw = payload.get("profile", payload)
        try:
            profile = self.store.import_dict(raw, overwrite=overwrite)
        except ProfileError as error:
            self._json(
                400,
                {
                    "ok": False,
                    "error": str(error),
                    "issues": [issue.to_dict() for issue in error.issues],
                },
            )
            return
        except ValueError as error:
            self._error(400, str(error))
            return
        self._json(
            200,
            {
                "ok": True,
                "profile": profile.to_dict(),
                "summary": profile.to_summary(),
                "issues": [issue.to_dict() for issue in validate(profile)],
            },
        )

    def _post_profile_delete(self) -> None:
        payload, error = self._read_json()
        if error:
            self._error(400, error)
            return
        assert payload is not None
        profile_id = payload.get("id")
        if not isinstance(profile_id, str) or not profile_id:
            self._error(400, "字段 id 必须是非空字符串")
            return
        if self.store.get(profile_id) is None:
            self._error(404, f"没有这个判断类型：{profile_id}")
            return
        if not self.store.delete(profile_id):
            self._error(400, f"「{profile_id}」是内置类型，删不掉 —— 内置类型只读")
            return
        self._json(200, {"ok": True, "deleted": profile_id})

    def _post_profile_import(self) -> None:
        payload, error = self._read_json()
        if error:
            self._error(400, error)
            return
        assert payload is not None
        overwrite = bool(payload.get("overwrite", False))
        raw = payload.get("profile", payload)
        try:
            profile = self.store.import_dict(raw, overwrite=overwrite)
        except ProfileError as error:
            self._json(
                400,
                {"ok": False, "error": str(error), "issues": [i.to_dict() for i in error.issues]},
            )
            return
        except ValueError as error:
            self._error(400, str(error))
            return
        self._json(200, {"ok": True, "profile": profile.to_dict(), "summary": profile.to_summary()})


def serve(
    host: str,
    port: int,
    model_dir: Path,
    revision: str,
    device: str,
    store: ProfileStore | None = None,
) -> None:
    print(f"[tiaoyige] 目标设备: {pick_device(device)}")
    print(f"[tiaoyige] 加载模型: {model_dir}")
    engine = Tiaoyige(model_dir=model_dir, revision=revision, device=device)
    engine.load()
    print(
        f"[tiaoyige] 模型就绪，用时 {engine.load_seconds:.1f}s "
        f"({engine.metadata.get('device')}, {engine.metadata.get('dtype')})"
    )
    store = store or ProfileStore()
    profiles = store.list()
    print(f"[tiaoyige] 判断类型 {len(profiles)} 套: " + "、".join(p.name for p in profiles))
    print(f"[tiaoyige] 词表（八艺）: {''.join(label['id'] for label in MEME_LABELS)}")
    probe = engine.decide("预热文本")
    print(f"[tiaoyige] 一次判定约 {probe['forward_ms']:.0f} ms（{probe['permutations']} 排列）")

    Handler.engine = engine
    Handler.store = store
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    print(f"[tiaoyige] 页面地址: http://{host}:{port}/", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[tiaoyige] 收到中断，正在退出")
    finally:
        httpd.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="帮你挑一个 —— 给一段文本，从你定义的一组选项里挑一个")
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
    parser.add_argument(
        "--profiles-dir",
        type=Path,
        default=None,
        help="用户自定义判断类型的存放目录（默认 data/profiles）",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="模型就绪后自动打开浏览器（release 包里的启动器会带上这个参数）",
    )
    args = parser.parse_args()

    model_dir, revision = args.model_dir, args.revision
    if args.model:
        name, revision = MODEL_CHOICES[args.model]
        model_dir = PROJECT_ROOT / "models" / name

    if args.open_browser:
        _open_browser_later(f"http://{args.host}:{args.port}/")
    serve(
        args.host,
        args.port,
        model_dir,
        revision,
        args.device,
        ProfileStore(user_dir=args.profiles_dir) if args.profiles_dir else None,
    )


def _open_browser_later(url: str) -> None:
    """模型加载要几十秒，等页面真的起来了再开浏览器。

    只在交互式启动（release 包里的双击启动）时有用；用线程是为了不挡住
    ``serve()`` 的模型加载。
    """
    import threading
    import urllib.error
    import urllib.request
    import webbrowser

    def wait_and_open() -> None:
        for _ in range(600):  # 最多等 5 分钟
            try:
                with urllib.request.urlopen(url + "api/health", timeout=2):
                    break
            except (urllib.error.URLError, OSError):
                time.sleep(0.5)
        else:
            return
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - 开不了浏览器不该影响服务
            pass

    threading.Thread(target=wait_and_open, daemon=True).start()


if __name__ == "__main__":
    main()
