"""HTTP 层的参数校验。

用一个**假引擎**跑，不加载模型、不占显存，所以秒回。
测的是「坏输入会不会被挡住」—— 真引擎的输出质量由 `scripts/evaluate.py` 管。
"""

from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from jev_meme.server import Handler, MAX_BODY_BYTES, MAX_TEXT_CHARS  # noqa: E402


class FakeEngine:
    """只实现 Handler 用得到的那几个成员。"""

    def __init__(self) -> None:
        self.loaded = True
        self.load_seconds = 0.0
        self.metadata = {"device": "cpu", "dtype": "float32", "source": "/fake/model"}
        self.calls: list[tuple[str, int]] = []

    def decide(self, text: str, permutations: int = 5) -> dict:
        if text == "炸":
            raise ValueError("待判定的文本不能为空")
        if text == "崩":
            raise RuntimeError("模拟的意外错误")
        self.calls.append((text, permutations))
        return {
            "winner": "典",
            "confidence": 0.9,
            "margin": 0.8,
            "ranking": [{"id": "典", "probability": 0.9, "logit": 1.0}],
            "input_tokens": 1000,
            "permutations": permutations,
            "permutations_requested": permutations,
            "batch": permutations,
            "forward_ms": 1.0,
            "total_ms": 2.0,
        }


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # 测试时把访问日志关掉，否则每个断言都夹一行 stderr，看不出失败在哪。
        Handler.log_message = lambda self, fmt, *args: None  # type: ignore[method-assign]
        Handler.engine = FakeEngine()
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()

    # ------------------------------------------------------------ 工具

    @classmethod
    def url(cls, path: str) -> str:
        return f"http://127.0.0.1:{cls.port}{path}"

    def get(self, path: str) -> tuple[int, dict]:
        try:
            with urllib.request.urlopen(self.url(path), timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))

    def post(self, path: str, payload, raw: bytes | None = None) -> tuple[int, dict]:
        body = raw if raw is not None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.url(path),
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode("utf-8"))


class TestHealth(ServerCase):
    def test_health(self):
        status, body = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["labels"]), 8)

    def test_labels(self):
        status, body = self.get("/api/labels")
        self.assertEqual(status, 200)
        self.assertEqual([x["id"] for x in body["labels"]], list("典孝急乐蚌批赢麻"))
        self.assertEqual(len(body["examples"]), 8)

    def test_index_served(self):
        with urllib.request.urlopen(self.url("/"), timeout=10) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("text/html", response.headers["Content-Type"])

    def test_unknown_path_404(self):
        status, body = self.get("/api/nope")
        self.assertEqual(status, 404)
        self.assertFalse(body["ok"])


class TestDecideValidation(ServerCase):
    def test_happy_path(self):
        status, body = self.post("/api/decide", {"text": "随便一句话", "permutations": 5})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertIn("server_ms", body)

    def test_default_permutations(self):
        """不传 permutations 时应当走默认档（5），而不是悄悄变成 1。"""
        engine = Handler.engine
        engine.calls.clear()
        self.post("/api/decide", {"text": "默认档"})
        self.assertEqual(engine.calls[-1][1], 5)

    def test_missing_text(self):
        status, body = self.post("/api/decide", {})
        self.assertEqual(status, 400)
        self.assertIn("text", body["error"])

    def test_blank_text(self):
        status, _ = self.post("/api/decide", {"text": "   "})
        self.assertEqual(status, 400)

    def test_text_not_string(self):
        status, _ = self.post("/api/decide", {"text": 123})
        self.assertEqual(status, 400)

    def test_text_too_long(self):
        status, body = self.post("/api/decide", {"text": "啊" * (MAX_TEXT_CHARS + 1)})
        self.assertEqual(status, 400)
        self.assertIn("太长", body["error"])

    def test_permutations_not_int(self):
        status, _ = self.post("/api/decide", {"text": "x", "permutations": "5"})
        self.assertEqual(status, 400)

    def test_permutations_bool_rejected(self):
        """`True` 是 int 的子类 —— 不显式挡掉的话会变成 permutations=1。"""
        status, _ = self.post("/api/decide", {"text": "x", "permutations": True})
        self.assertEqual(status, 400)

    def test_permutations_out_of_range(self):
        for value in (0, -1, 17, 999):
            with self.subTest(value=value):
                status, _ = self.post("/api/decide", {"text": "x", "permutations": value})
                self.assertEqual(status, 400)

    def test_profile_only_bayi(self):
        status, _ = self.post("/api/decide", {"text": "x", "profile": "classic"})
        self.assertEqual(status, 400)

    def test_bad_json(self):
        status, body = self.post("/api/decide", None, raw=b"{not json")
        self.assertEqual(status, 400)
        self.assertIn("JSON", body["error"])

    def test_body_must_be_object(self):
        status, _ = self.post("/api/decide", None, raw=b"[1,2,3]")
        self.assertEqual(status, 400)

    def test_body_too_large(self):
        status, body = self.post("/api/decide", None, raw=b"x" * (MAX_BODY_BYTES + 1))
        self.assertEqual(status, 400)
        self.assertIn("字节", body["error"])

    def test_value_error_becomes_400(self):
        status, body = self.post("/api/decide", {"text": "炸"})
        self.assertEqual(status, 400)
        self.assertIn("不能为空", body["error"])

    def test_unexpected_error_becomes_500(self):
        status, body = self.post("/api/decide", {"text": "崩"})
        self.assertEqual(status, 500)
        self.assertFalse(body["ok"])

    def test_wrong_method_on_decide(self):
        status, _ = self.get("/api/decide")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
