"""HTTP 层的参数校验。

用一个**假引擎**跑，不加载模型、不占显存，所以秒回。
测的是「坏输入会不会被挡住」—— 真引擎的输出质量由 `scripts/evaluate.py` 管。
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from biaochi.profiles import ProfileStore  # noqa: E402
from biaochi.server import Handler, MAX_BODY_BYTES, MAX_TEXT_CHARS  # noqa: E402


class FakeEngine:
    """只实现 Handler 用得到的那几个成员。"""

    def __init__(self) -> None:
        self.loaded = True
        self.load_seconds = 0.0
        self.metadata = {"device": "cpu", "dtype": "float32", "source": "/fake/model"}
        self.calls: list[tuple[str, int, str | None]] = []

    def decide(self, text: str, permutations: int = 5, profile=None) -> dict:
        if text == "炸":
            raise ValueError("待判定的文本不能为空")
        if text == "崩":
            raise RuntimeError("模拟的意外错误")
        self.calls.append((text, permutations, getattr(profile, "id", None)))
        label = profile.labels[0]["id"] if profile is not None else "典"
        return {
            "winner": label,
            "confidence": 0.9,
            "margin": 0.8,
            "ranking": [{"id": label, "probability": 0.9, "logit": 1.0}],
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
        # 用户类型写到临时目录 —— 测试绝不能碰仓库里的 data/profiles。
        cls._tmp = tempfile.TemporaryDirectory()
        cls.profile_dir = Path(cls._tmp.name)
        Handler.store = ProfileStore(user_dir=cls.profile_dir)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.httpd.daemon_threads = True
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls._tmp.cleanup()

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

    def get_raw(self, path: str):
        with urllib.request.urlopen(self.url(path), timeout=10) as response:
            return response.status, response.headers, response.read()


class TestEvalEndpoint(ServerCase):
    """`/api/eval` 是网页头条数字的唯一出处。"""

    def test_returns_available_flag(self):
        status, body = self.get("/api/eval")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertIn("available", body)

    def test_payload_is_consistent_when_present(self):
        _, body = self.get("/api/eval")
        if not body.get("available"):
            self.skipTest("还没跑过 evaluate.py --write-result")
        self.assertGreater(body["total"], 0)
        self.assertAlmostEqual(
            body["accuracy"], body["correct"] / body["total"], places=4
        )
        low, high = body["ci95"]
        self.assertLessEqual(low, body["accuracy"])
        self.assertGreaterEqual(high, body["accuracy"])


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

    def test_unknown_profile_rejected(self):
        """从前这里只认 `bayi`；现在类型可自定义，认的是「存不存在」。"""
        status, body = self.post("/api/decide", {"text": "x", "profile": "classic"})
        self.assertEqual(status, 400)
        self.assertIn("判断类型", body["error"])

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


def sample_profile(profile_id: str = "demo") -> dict:
    """一份合法的最小自定义类型 —— 页面上「新建」出来的就长这样。"""
    return {
        "id": profile_id,
        "name": "演示类型",
        "summary": "测试用",
        "criterion": "下面这句话最符合哪一类？",
        "version": "v1",
        "labels": [
            {
                "id": "甲",
                "description": "这段话在举例。例：「比如昨天那件事」「举个例子」。",
                "hint": "举例",
            },
            {
                "id": "乙",
                "description": "这段话在下结论。例：「所以就是这样」「结论很清楚」。",
                "hint": "下结论",
            },
        ],
        "examples": [{"label": "甲", "text": "比如上次那个情况。"}],
    }


class TestProfilesEndpoint(ServerCase):
    """判断类型的增删改查 —— 页面的词表编辑器打的就是这几个接口。"""

    def test_list_includes_builtin(self):
        status, body = self.get("/api/profiles")
        self.assertEqual(status, 200)
        ids = [item["id"] for item in body["profiles"]]
        self.assertIn("bayi", ids)
        self.assertIn("support-router", ids)
        self.assertEqual(body["default"], "bayi")

    def test_get_bayi_has_eight_labels(self):
        status, body = self.get("/api/profiles/bayi")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["profile"]["labels"]), 8)
        self.assertTrue(body["profile"]["builtin"])
        self.assertIn("stats", body)
        self.assertIsInstance(body["issues"], list)

    def test_get_missing_profile_404(self):
        status, body = self.get("/api/profiles/nope")
        self.assertEqual(status, 404)
        self.assertFalse(body["ok"])

    def test_export_sets_attachment_filename(self):
        status, headers, raw = self.get_raw("/api/profiles/bayi/export")
        self.assertEqual(status, 200)
        self.assertIn("attachment", headers["Content-Disposition"])
        self.assertIn("bayi.json", headers["Content-Disposition"])
        self.assertEqual(json.loads(raw.decode("utf-8"))["id"], "bayi")

    def test_validate_reports_errors_without_saving(self):
        bad = sample_profile("bad-demo")
        bad["labels"] = [bad["labels"][0]]  # 只剩一个选项
        status, body = self.post("/api/profiles/validate", {"profile": bad})
        self.assertEqual(status, 200)
        self.assertGreater(body["error_count"], 0)
        self.assertEqual(self.get("/api/profiles/bad-demo")[0], 404)

    def test_save_then_get_then_delete(self):
        profile = sample_profile("demo-roundtrip")
        status, body = self.post("/api/profiles", {"profile": profile})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["summary"]["id"], "demo-roundtrip")
        self.assertTrue(self.profile_dir.joinpath("demo-roundtrip.json").is_file())

        status, body = self.get("/api/profiles/demo-roundtrip")
        self.assertEqual(status, 200)
        self.assertEqual([x["id"] for x in body["profile"]["labels"]], ["甲", "乙"])

        status, body = self.post("/api/profiles/delete", {"id": "demo-roundtrip"})
        self.assertEqual(status, 200)
        self.assertEqual(self.get("/api/profiles/demo-roundtrip")[0], 404)

    def test_save_refuses_overwrite_without_flag(self):
        profile = sample_profile("demo-overwrite")
        self.assertEqual(self.post("/api/profiles", {"profile": profile})[0], 200)
        profile["name"] = "改过名"
        status, body = self.post("/api/profiles", {"profile": profile})
        self.assertEqual(status, 400)
        self.assertIn("覆盖", body["error"])
        status, _ = self.post("/api/profiles", {"profile": profile, "overwrite": True})
        self.assertEqual(status, 200)
        self.assertEqual(self.get("/api/profiles/demo-overwrite")[1]["profile"]["name"], "改过名")
        self.post("/api/profiles/delete", {"id": "demo-overwrite"})

    def test_save_rejects_invalid_profile_with_issues(self):
        profile = sample_profile("demo-invalid")
        profile["criterion"] = ""
        status, body = self.post("/api/profiles", {"profile": profile})
        self.assertEqual(status, 400)
        self.assertTrue(any(issue["field"] == "criterion" for issue in body["issues"]))

    def test_cannot_delete_builtin(self):
        status, body = self.post("/api/profiles/delete", {"id": "bayi"})
        self.assertEqual(status, 400)
        self.assertIn("内置", body["error"])

    def test_delete_missing_404(self):
        self.assertEqual(self.post("/api/profiles/delete", {"id": "nope"})[0], 404)

    def test_import_roundtrip(self):
        exported = self.get_raw("/api/profiles/support-router/export")[2].decode("utf-8")
        raw = json.loads(exported)
        raw["id"] = "support-router-copy"
        status, body = self.post("/api/profiles/import", {"profile": raw})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["summary"]["label_count"], 5)
        self.post("/api/profiles/delete", {"id": "support-router-copy"})

    def test_import_without_id_400(self):
        status, body = self.post("/api/profiles/import", {"profile": {"name": "没 id"}})
        self.assertEqual(status, 400)


class TestDecideWithProfiles(ServerCase):
    def test_decide_uses_named_profile(self):
        engine = Handler.engine
        engine.calls.clear()
        status, body = self.post(
            "/api/decide", {"text": "我的快递到哪了", "profile": "support-router"}
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["profile"], "support-router")
        self.assertEqual(engine.calls[-1][2], "support-router")
        # 判定结果用的是这套类型自己的第一个选项，不是「八艺」的「典」。
        self.assertEqual(body["winner"], "退款")

    def test_decide_defaults_to_bayi(self):
        engine = Handler.engine
        engine.calls.clear()
        status, body = self.post("/api/decide", {"text": "随便一句话"})
        self.assertEqual(status, 200)
        self.assertEqual(body["profile"], "bayi")
        self.assertEqual(engine.calls[-1][2], "bayi")

    def test_decide_with_inline_labels(self):
        """编辑器里改了还没保存的词表也要能试判 —— 不然「改了立刻看效果」做不到。"""
        engine = Handler.engine
        engine.calls.clear()
        status, body = self.post(
            "/api/decide",
            {
                "text": "试一句",
                "inline": {
                    "criterion": "选一个",
                    "labels": [
                        {"id": "甲", "description": "例：「甲」"},
                        {"id": "乙", "description": "例：「乙」"},
                    ],
                },
            },
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["winner"], "甲")
        self.assertEqual(engine.calls[-1][2], "inline")

    def test_inline_requires_two_labels(self):
        status, body = self.post(
            "/api/decide",
            {"text": "x", "inline": {"criterion": "选一个", "labels": [{"id": "甲", "description": "d"}]}},
        )
        self.assertEqual(status, 400)
        self.assertIn("2~16", body["error"])

    def test_inline_requires_criterion(self):
        status, _ = self.post(
            "/api/decide",
            {
                "text": "x",
                "inline": {
                    "criterion": "",
                    "labels": [{"id": "甲", "description": "d"}, {"id": "乙", "description": "d"}],
                },
            },
        )
        self.assertEqual(status, 400)

    def test_inline_rejects_duplicate_ids(self):
        status, body = self.post(
            "/api/decide",
            {
                "text": "x",
                "inline": {
                    "criterion": "选一个",
                    "labels": [{"id": "甲", "description": "d"}, {"id": "甲", "description": "d"}],
                },
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("重复", body["error"])

    def test_eval_endpoint_is_profile_aware(self):
        status, body = self.get("/api/eval?profile=support-router")
        self.assertEqual(status, 200)
        self.assertEqual(body["profile"], "support-router")
        self.assertFalse(body["available"])
        self.assertIn("how", body)

    def test_eval_rejects_path_traversal(self):
        """`profile` 会拼进文件名，所以必须在路由层挡掉。

        回归：`?profile=../eval_result` 曾经真的读出了 `data/eval_result.json`。
        """
        for bad in ("../eval_result", "..%2Feval_result", "a/b", "Bayi"):
            with self.subTest(bad=bad):
                status, body = self.get(f"/api/eval?profile={bad}")
                self.assertEqual(status, 400)
                self.assertFalse(body["ok"])


if __name__ == "__main__":
    unittest.main()
