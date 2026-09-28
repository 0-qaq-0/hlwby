"""判断类型（profile）：数据模型、校验规则、存取。

这里最有价值的一组断言是 `TestBuiltinProfiles`：**内置类型必须永远是合法的**。
它们是随包发出去的东西，如果连自己的校验都过不了，用户打开编辑器第一眼
就是一片红。把这条钉在测试里，改锚点时就不会悄悄改坏。

另一组是 `TestValidateRules`：`docs/EVAL.md` 里那些实测结论（泛化短语是吸铁石、
提到别的选项名会漏概率、示例抄锚点等于自问自答）现在是可执行的检查，
所以它们也得有测试 —— 否则「检查」本身会腐烂。
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from biaochi.labels import CRITERION, EXAMPLES, MEME_LABELS  # noqa: E402
from biaochi.profiles import (  # noqa: E402
    DEFAULT_PROFILE_ID,
    MAX_LABELS,
    Profile,
    ProfileError,
    ProfileStore,
    errors_of,
    eval_result_path,
    profile_stats,
    validate,
)


def make_profile(profile_id: str = "demo", **overrides) -> Profile:
    base = Profile(
        id=profile_id,
        name="演示",
        summary="测试用",
        criterion="下面这句话最符合哪一类？",
        labels=[
            {"id": "甲", "description": "这段话在举例。例：「比如昨天那件事」「举个例子」。", "hint": "举例"},
            {"id": "乙", "description": "这段话在下结论。例：「所以就是这样」「结论很清楚」。", "hint": "下结论"},
        ],
        examples=[{"label": "甲", "text": "比如上次那个情况。"}],
        version="v1",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


class TestBuiltinProfiles(unittest.TestCase):
    """内置类型是随包发出去的东西，必须一直是合法的。"""

    def setUp(self):
        self.store = ProfileStore()
        self.profiles = self.store.list()

    def test_has_default_and_examples(self):
        ids = [profile.id for profile in self.profiles]
        self.assertIn(DEFAULT_PROFILE_ID, ids)
        self.assertGreaterEqual(len(self.profiles), 3, "至少要有八艺 + 两个示例类型")

    def test_all_builtins_are_valid(self):
        for profile in self.profiles:
            with self.subTest(profile=profile.id):
                errors = errors_of(validate(profile))
                self.assertEqual(errors, [], f"{profile.id} 有校验错误：{errors}")

    def test_bayi_is_labels_py_verbatim(self):
        """「八艺」的权威出处是 labels.py —— profile 只是它的一个视图。"""
        bayi = self.store.get(DEFAULT_PROFILE_ID)
        assert bayi is not None
        self.assertEqual(bayi.criterion, CRITERION)
        self.assertEqual([dict(x) for x in bayi.labels], [dict(x) for x in MEME_LABELS])
        self.assertEqual([dict(x) for x in bayi.examples], [dict(x) for x in EXAMPLES])
        self.assertTrue(bayi.builtin)
        self.assertTrue(bayi.evaluated)

    def test_example_profiles_are_marked_unevaluated(self):
        """示例类型不能冒充评测过的类型 —— 页面上会显示「未评测」徽标。"""
        for profile in self.profiles:
            if profile.id == DEFAULT_PROFILE_ID:
                continue
            with self.subTest(profile=profile.id):
                self.assertFalse(profile.evaluated)
                self.assertTrue(profile.note)

    def test_example_profiles_have_examples_for_every_label(self):
        for profile in self.profiles:
            with self.subTest(profile=profile.id):
                covered = {example["label"] for example in profile.examples}
                self.assertEqual(covered, set(profile.label_ids))


class TestProfileData(unittest.TestCase):
    def test_roundtrip(self):
        # 先过一遍 from_dict 把字段补齐，再比 —— 手写的 label 少了 name/accent，
        # 而读进来的一定会被补全，那是设计如此。
        once = Profile.from_dict(make_profile().to_dict())
        twice = Profile.from_dict(once.to_dict())
        self.assertEqual(twice.to_dict(), once.to_dict())

    def test_from_dict_unwraps_export_envelope(self):
        raw = {"profile": make_profile().to_dict()}
        self.assertEqual(Profile.from_dict(raw).id, "demo")

    def test_from_dict_fills_defaults(self):
        profile = Profile.from_dict({"id": "x1", "name": "x", "criterion": "选", "labels": [{"id": "甲"}]})
        label = profile.labels[0]
        self.assertEqual(label["name"], "甲")
        self.assertEqual(label["accent"], "#6ea8fe")
        self.assertEqual(label["description"], "")
        self.assertEqual(profile.version, "v1")

    def test_from_dict_rejects_non_object(self):
        with self.assertRaises(ValueError):
            Profile.from_dict([1, 2, 3])

    def test_from_dict_skips_blank_examples(self):
        profile = Profile.from_dict(
            {"id": "x1", "name": "x", "labels": [], "examples": [{"label": "甲", "text": "  "}]}
        )
        self.assertEqual(profile.examples, [])

    def test_summary_is_lightweight(self):
        summary = make_profile().to_summary()
        self.assertNotIn("labels", summary)
        self.assertEqual(summary["label_ids"], ["甲", "乙"])
        self.assertEqual(summary["label_count"], 2)


class TestValidateRules(unittest.TestCase):
    def test_clean_profile_has_no_errors(self):
        self.assertEqual(errors_of(validate(make_profile())), [])

    def test_id_must_be_a_slug(self):
        for bad in ("", "Demo", "有中文", "x", "-lead", "a" * 60):
            with self.subTest(bad=bad):
                self.assertTrue(errors_of(validate(make_profile(bad))))

    def test_name_and_criterion_required(self):
        self.assertTrue(errors_of(validate(make_profile("demo1", name=""))))
        self.assertTrue(errors_of(validate(make_profile("demo1", criterion=""))))

    def test_label_count_bounds(self):
        one = make_profile("demo1", labels=[{"id": "甲", "description": "例：「a」", "hint": ""}])
        self.assertTrue(errors_of(validate(one)))
        many = make_profile(
            "demo1",
            labels=[
                {"id": f"L{i}", "description": "例：「a」", "hint": ""} for i in range(MAX_LABELS + 1)
            ],
        )
        self.assertTrue(errors_of(validate(many)))

    def test_duplicate_label_ids_rejected(self):
        profile = make_profile(
            "demo1",
            labels=[
                {"id": "甲", "description": "例：「a」", "hint": ""},
                {"id": "甲", "description": "例：「b」", "hint": ""},
            ],
        )
        messages = " ".join(issue.message for issue in errors_of(validate(profile)))
        self.assertIn("重复", messages)

    def test_empty_description_rejected(self):
        profile = make_profile(
            "demo1",
            labels=[
                {"id": "甲", "description": "", "hint": ""},
                {"id": "乙", "description": "例：「b」", "hint": ""},
            ],
        )
        self.assertTrue(errors_of(validate(profile)))

    def test_example_must_point_at_a_real_label(self):
        profile = make_profile("demo1", examples=[{"label": "丙", "text": "随便一句"}])
        messages = " ".join(issue.message for issue in errors_of(validate(profile)))
        self.assertIn("不存在", messages)

    # ------------------------------------------------------ 经验性检查（warning）

    def warnings_for(self, profile: Profile) -> str:
        return " ".join(issue.message for issue in validate(profile) if issue.level == "warning")

    def test_generic_phrase_warns(self):
        """「一段不长不短的普通论述」是吸铁石 —— 实测删掉它准确率 +7.7 个百分点。"""
        profile = make_profile(
            "demo1",
            labels=[
                {"id": "甲", "description": "这段话在讲道理，是一段不长不短的普通论述。例：「a」", "hint": ""},
                {"id": "乙", "description": "例：「b」「c」", "hint": ""},
            ],
        )
        self.assertIn("泛化短语", self.warnings_for(profile))

    def test_cross_reference_warns(self):
        """描述里提别的选项名会把概率漏过去。"""
        profile = make_profile(
            "demo1",
            labels=[
                {"id": "甲", "description": "这段话不是「乙」，是在举例。例：「a」「b」", "hint": ""},
                {"id": "乙", "description": "例：「c」「d」", "hint": ""},
            ],
        )
        self.assertIn("另一个选项", self.warnings_for(profile))

    def test_single_char_id_is_not_a_false_positive(self):
        """「典型」里有「典」—— 单字 id 的偶然子串不能算跨引用。"""
        profile = make_profile(
            "demo1",
            labels=[
                {"id": "典", "description": "这段话很典型，是在举例。例：「a」「b」", "hint": ""},
                {"id": "乙", "description": "例：「c」「d」", "hint": ""},
            ],
        )
        self.assertNotIn("另一个选项", self.warnings_for(profile))

    def test_no_examples_warns(self):
        profile = make_profile("demo1", examples=[])
        self.assertIn("示例", self.warnings_for(profile))

    def test_example_copying_anchor_warns(self):
        """示例抄锚点 = 自问自答，必对，零信息量 —— 这正是当年 96% 假数字的成因。"""
        anchor = "这段话在夸某个公司、品牌、平台、老板或名人，替他说话、替他辩解。"
        profile = make_profile(
            "demo1",
            labels=[
                {"id": "甲", "description": anchor + "例：「a」「b」", "hint": ""},
                {"id": "乙", "description": "例：「c」「d」", "hint": ""},
            ],
            examples=[{"label": "甲", "text": "这段话在夸某个公司、品牌、平台、老板或名人"}],
        )
        self.assertIn("字面重合", self.warnings_for(profile))

    def test_relational_criterion_warns(self):
        """关系式问法（「当对方…」）实测会塌缩到一个选项，只有 50%。"""
        profile = make_profile("demo1", criterion="当对方在辩论时，这段话属于哪一类？")
        self.assertIn("关系式", self.warnings_for(profile))

    def test_relational_description_warns(self):
        """锚点描述里写「当对方…」同样会塌缩 —— 这条教训不能只在问法上查。"""
        profile = make_profile(
            "demo1",
            labels=[
                {"id": "甲", "description": "当对方在辩论时，选这个。例：「a」「b」", "hint": ""},
                {"id": "乙", "description": "例：「c」「d」", "hint": ""},
            ],
        )
        self.assertIn("关系式", self.warnings_for(profile))

    def test_unevaluated_warns(self):
        self.assertIn("评测", self.warnings_for(make_profile()))

    def test_warnings_do_not_block_saving(self):
        profile = make_profile("demo1", examples=[])
        self.assertEqual(errors_of(validate(profile)), [])
        self.assertTrue([i for i in validate(profile) if i.level == "warning"])

    def test_validate_never_crashes_on_junk(self):
        profile = Profile.from_dict({"id": "demo1", "labels": [{"id": ""}, {"id": "乙"}]})
        validate(profile)  # 不抛异常就算过


class TestProfileStats(unittest.TestCase):
    def test_counts(self):
        stats = profile_stats(make_profile())
        self.assertEqual(stats["label_count"], 2)
        self.assertEqual(stats["example_count"], 1)
        self.assertGreater(stats["prompt_chars"], 0)
        self.assertGreater(stats["anchor_examples"], 0)

    def test_empty_profile_is_all_zero(self):
        stats = profile_stats(Profile(id="x1", name="x"))
        self.assertEqual(stats["label_count"], 0)
        self.assertEqual(stats["description_min"], 0)


class TestProfileStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.store = ProfileStore(user_dir=self.dir)

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_get_list_delete(self):
        self.store.save(make_profile("mine"))
        self.assertIsNotNone(self.store.get("mine"))
        self.assertTrue((self.dir / "mine.json").is_file())
        self.assertIn("mine", [profile.id for profile in self.store.list()])
        self.assertTrue(self.store.delete("mine"))
        self.assertIsNone(self.store.get("mine"))
        self.assertFalse(self.store.delete("mine"))

    def test_saved_file_is_valid_json(self):
        self.store.save(make_profile("mine"))
        raw = json.loads((self.dir / "mine.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["schema"], 1)
        self.assertEqual(raw["id"], "mine")
        self.assertFalse(raw["builtin"])
        self.assertTrue(raw["updated_at"])

    def test_overwrite_needs_flag(self):
        self.store.save(make_profile("mine"))
        with self.assertRaises(ProfileError):
            self.store.save(make_profile("mine"))
        self.store.save(make_profile("mine", name="改名了"), overwrite=True)
        self.assertEqual(self.store.get("mine").name, "改名了")

    def test_cannot_overwrite_builtin(self):
        with self.assertRaises(ProfileError):
            self.store.save(ProfileStore().get(DEFAULT_PROFILE_ID))

    def test_cannot_take_builtin_id(self):
        with self.assertRaises(ProfileError):
            self.store.save(make_profile(DEFAULT_PROFILE_ID))

    def test_invalid_profile_is_rejected_with_issues(self):
        with self.assertRaises(ProfileError) as caught:
            self.store.save(make_profile("mine", criterion=""))
        self.assertTrue(caught.exception.issues)

    def test_user_profile_cannot_shadow_builtin(self):
        """就算有人手写了一个 bayi.json，也不能顶掉内置的那份。"""
        (self.dir / "bayi.json").write_text(
            json.dumps(make_profile("bayi").to_dict(), ensure_ascii=False), encoding="utf-8"
        )
        bayi = self.store.get("bayi")
        self.assertTrue(bayi.builtin)
        self.assertEqual(len(bayi.labels), 8)

    def test_broken_user_file_is_skipped(self):
        (self.dir / "broken.json").write_text("{ 这不是 JSON", encoding="utf-8")
        self.assertIsNone(self.store.get("broken"))
        self.assertIsNotNone(self.store.get(DEFAULT_PROFILE_ID))

    def test_export_import_roundtrip(self):
        self.store.save(make_profile("mine"))
        exported = self.store.export_dict("mine")
        exported["id"] = "mine2"
        imported = self.store.import_dict(exported)
        self.assertEqual(imported.id, "mine2")
        self.assertEqual(imported.labels, self.store.get("mine").labels)

    def test_export_missing_raises(self):
        with self.assertRaises(ProfileError):
            self.store.export_dict("nope")

    def test_import_without_id_raises(self):
        with self.assertRaises(ProfileError):
            self.store.import_dict({"name": "没 id"})

    def test_missing_user_dir_is_fine(self):
        store = ProfileStore(user_dir=self.dir / "not-created-yet")
        self.assertEqual([p.id for p in store.list()], [p.id for p in ProfileStore().list()])

    def test_filename_wins_over_inner_id(self):
        """手写的 JSON 里 id 和文件名不一致时，以文件名为准。

        否则会出现两种很难查的现象：`delete("bar")` 删不掉（它按文件名找），
        以及列表里冒出两个 id 都是 `bar` 的条目。
        """
        (self.dir / "foo.json").write_text(
            json.dumps(make_profile("bar").to_dict(), ensure_ascii=False), encoding="utf-8"
        )
        self.assertIsNotNone(self.store.get("foo"))
        self.assertIsNone(self.store.get("bar"))
        ids = [profile.id for profile in self.store.list()]
        self.assertEqual(len(ids), len(set(ids)), f"列表里有重复 id：{ids}")
        self.assertTrue(self.store.delete("foo"))
        self.assertFalse((self.dir / "foo.json").is_file())


class TestEvalResultPath(unittest.TestCase):
    """id 会拼进文件名，所以必须挡路径穿越。"""

    def test_default_profile_uses_the_historic_file(self):
        self.assertEqual(eval_result_path("bayi").name, "eval_result.json")

    def test_custom_profile_goes_to_the_results_dir(self):
        self.assertEqual(eval_result_path("support-router").parent.name, "eval_results")

    def test_traversal_is_rejected(self):
        for bad in ("../eval_result", "..\\eval_result", "a/b", "", "Bayi", "x" * 60):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    eval_result_path(bad)


if __name__ == "__main__":
    unittest.main()
