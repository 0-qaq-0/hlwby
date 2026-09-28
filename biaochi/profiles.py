"""判断类型（profile）—— 「判定什么」本身是可以改的。

## 为什么要有这一层

这套系统的全部「训练」就是**推理时才读进去的几段文字**：判定问法（criterion）、
每个选项的锚点描述（description）、页面示例。既然它们是运行时数据，
那「判断类型」本身就该是运行时的 —— 想判八艺就判八艺，想判客服分流、
内容处置、情绪分类，改的是数据，不是权重，更不用重训。

一个 profile 就是打包好的这一套：

    id / name / summary     身份
    criterion               判定问法
    labels[]                选项：id + 锚点描述 + 人话提示 + 配色
    examples[]              页面示例（点一下就能试）
    version                 锚点版本：改了措辞就该改它，否则「这个数字是哪版测的」说不清
    evaluated               有没有在干净测试集上评测过

## 校验：把踩过的坑写成检查

`docs/EVAL.md` 里那些实测结论不该只活在文档里。`validate()` 把它们变成
**可执行的检查**，用户改锚点时当场就能看到：

  * 描述太泛（「一段不长不短的普通论述」）—— 吸铁石，实测删掉它 +7.7 个百分点；
  * 描述写成关系式（「当对方辩论时」）—— 实测只有 50%，改成描述文本形态才到 96%；
  * 描述里提到别的选项名 —— 概率会漏给那个选项；
  * 没有例句、只写抽象定义 —— 实测 23% vs 96%；
  * 示例和锚点例句逐字重合 —— 自问自答，测出来的数字没有意义。

error 拦住保存，warning 只提示 —— 因为这些都是**经验**不是定理，
用户可能确实知道自己在干什么。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .labels import CRITERION, EXAMPLES, MEME_LABELS
from .textcheck import LEAK_THRESHOLD, WARN_THRESHOLD, overlap
from .version import SCHEMA_VERSION

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BUILTIN_DIR = Path(__file__).resolve().parent / "builtin_profiles"
USER_DIR = PROJECT_ROOT / "data" / "profiles"

#: 评测结果落在哪：一整套类型一个文件。
#:
#: 「八艺」是项目自带的那套，历史文件在 `data/eval_result.json`（README 和页面
#: 引用了很久，不能挪）；自定义类型走 `data/eval_results/<id>.json`。
EVAL_RESULT = PROJECT_ROOT / "data" / "eval_result.json"
EVAL_DIR = PROJECT_ROOT / "data" / "eval_results"


def eval_result_path(profile_id: str) -> Path:
    """某套判断类型的评测结果文件路径。

    id 会直接拼进文件名，所以**必须**先过一遍 ``SLUG_RE``：
    这个函数是拿 ``profile_id`` 当路径用的，而 ``profile_id`` 来自 URL 查询串。
    不加这层检查的话 `?profile=../eval_result` 能读到 `data/` 下的别的文件
    （实测确实能读到 —— 一个本地小工具也不该留这种口子）。
    """
    if profile_id == DEFAULT_PROFILE_ID:
        return EVAL_RESULT
    if not SLUG_RE.match(profile_id or ""):
        raise ValueError(f"判断类型 id 不合法：{profile_id!r}")
    return EVAL_DIR / f"{profile_id}.json"

#: 内置的「八艺」类型 —— 评测数字、README、页面默认值都挂在它身上。
DEFAULT_PROFILE_ID = "bayi"

#: 选项数量的硬边界：上游把选项绑到 ``A``–``P`` 这 16 个单 token 槽位上。
MIN_LABELS = 2
MAX_LABELS = 16

#: 选项 id 直接显示在概率条左边，太长会把版面撑坏。
MAX_LABEL_ID = 6

#: 用户类型 id 只允许小写字母数字下划线连字符 —— 它同时是文件名。
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,47}$")

#: 描述字数极差的**参考**上限。超了只提示，不算失败。
#:
#: 实测教训：为了把极差压到这条线以内而删锚点例句，「八艺」准确率从 96% 掉到 88%。
#: **锚点数量比长度均衡更重要。**
LENGTH_SPREAD_SOFT_LIMIT = 70

#: 「吸铁石」短语：对什么文本都成立，不是判别特征。
#:
#: 出处是 `docs/EVAL.md` 第三节：14 个错例里 11 个判成了「典」，
#: 因为「典」的描述里有一句「一段不长不短的普通论述」。
#: `scripts/anchor_tune.py` 做了剂量反应验证，删掉它准确率 73.1% -> 80.8%。
GENERIC_PHRASES: tuple[str, ...] = (
    "不长不短",
    "普通的论述",
    "一般的论述",
    "普通的评论",
    "一般的评论",
    "普通的一段",
    "有内容的发言",
    "正常的发言",
    "一般性的描述",
    "大多数评论",
    "不管什么",
    "常见的说法",
    "随便一句话",
    "任何一段",
)

#: 描述里出现这些词，说明写的是「说话人在干什么」而不是「文本长什么样」。
#:
#: 这是本项目最贵的一条教训：这套定义本身是关系式的（「当对方辩论时」），
#: 照字面写锚点会全部塌缩到「赢」，准确率只有 50%；改成描述文本形态之后跳到 96%。
RELATIONAL_HINTS: tuple[str, ...] = (
    "当对方",
    "如果对方",
    "说话人",
    "对方正在",
    "他在试图",
)

_QUOTE_PAIRS = (("「", "」"), ("『", "』"), ("“", "”"), ('"', '"'))


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------- 数据结构


@dataclass
class Issue:
    """一条校验结论。``level`` 是 ``error``（拦住保存）或 ``warning``（只提示）。"""

    level: str
    field: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"level": self.level, "field": self.field, "message": self.message}


@dataclass
class Profile:
    """一套判断类型。字段含义见模块开头。"""

    id: str
    name: str
    summary: str = ""
    criterion: str = ""
    labels: list[dict[str, str]] = field(default_factory=list)
    examples: list[dict[str, str]] = field(default_factory=list)
    version: str = "v1"
    note: str = ""
    builtin: bool = False
    evaluated: bool = False
    updated_at: str = ""

    # ------------------------------------------------------------ 序列化

    def to_dict(self) -> dict[str, Any]:
        """完整形式（存盘 / 导出用）。"""
        return {
            "schema": SCHEMA_VERSION,
            "id": self.id,
            "name": self.name,
            "summary": self.summary,
            "criterion": self.criterion,
            "version": self.version,
            "note": self.note,
            "labels": [dict(label) for label in self.labels],
            "examples": [dict(example) for example in self.examples],
            "builtin": self.builtin,
            "evaluated": self.evaluated,
            "updated_at": self.updated_at,
        }

    def to_summary(self) -> dict[str, Any]:
        """列表用的轻量形式 —— 不带锚点正文，列表页不需要。"""
        return {
            "id": self.id,
            "name": self.name,
            "summary": self.summary,
            "version": self.version,
            "label_count": len(self.labels),
            "label_ids": [label["id"] for label in self.labels],
            "example_count": len(self.examples),
            "builtin": self.builtin,
            "evaluated": self.evaluated,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Profile":
        """宽松地读入一份数据：缺字段补默认值，多余字段丢掉。

        「宽松」是刻意的 —— 这个函数的输入一半来自用户手写的 JSON 和
        浏览器里半成品状态，报「缺字段」不如先收下来再让 ``validate`` 说清楚。
        """
        if not isinstance(raw, dict):
            raise ValueError("profile 必须是一个 JSON 对象")
        # 允许直接喂导出文件：`{"profile": {...}}` 也认。
        if isinstance(raw.get("profile"), dict):
            raw = raw["profile"]

        labels = []
        for item in raw.get("labels") or []:
            if not isinstance(item, dict):
                continue
            label_id = str(item.get("id", "")).strip()
            labels.append(
                {
                    "id": label_id,
                    "name": str(item.get("name") or label_id).strip(),
                    "pinyin": str(item.get("pinyin", "")).strip(),
                    "description": str(item.get("description", "")).strip(),
                    "hint": str(item.get("hint", "")).strip(),
                    "accent": str(item.get("accent") or "#6ea8fe").strip(),
                }
            )

        examples = []
        for item in raw.get("examples") or []:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            examples.append({"label": str(item.get("label", "")).strip(), "text": text})

        return cls(
            id=str(raw.get("id", "")).strip(),
            name=str(raw.get("name", "")).strip(),
            summary=str(raw.get("summary", "")).strip(),
            criterion=str(raw.get("criterion", "")).strip(),
            labels=labels,
            examples=examples,
            version=str(raw.get("version") or "v1").strip(),
            note=str(raw.get("note", "")).strip(),
            builtin=bool(raw.get("builtin", False)),
            evaluated=bool(raw.get("evaluated", False)),
            updated_at=str(raw.get("updated_at", "")).strip(),
        )

    # ------------------------------------------------------------ 便捷读取

    @property
    def label_ids(self) -> list[str]:
        return [label["id"] for label in self.labels]

    def labels_by_id(self) -> dict[str, dict[str, str]]:
        return {label["id"]: label for label in self.labels}


# --------------------------------------------------------------------- 校验


def _quote_count(text: str) -> int:
    """数一下描述里有多少个成对的引号片段 —— 粗略代表「给了几个例句」。"""
    total = 0
    for left, right in _QUOTE_PAIRS:
        if left == right:
            total += text.count(left) // 2
        else:
            total += min(text.count(left), text.count(right))
    return total


def _mentions_other_labels(description: str, own_id: str, other_ids: list[str]) -> list[str]:
    """描述里有没有提到别的选项名。

    为什么单独判「引号包起来」和「不是 X」两种形态：选项 id 常常只有一个汉字
    （「典」），而「典型」「孝道」这类词里也会出现同一个字 —— 直接子串匹配
    会把正常描述全判成违规。所以只认**明确的引用**。
    """
    hits = []
    for other in other_ids:
        if other == own_id or not other:
            continue
        quoted = any(f"{left}{other}{right}" in description for left, right in _QUOTE_PAIRS)
        named = re.search(rf"(不是|区别于|不同于|而不是|并非)\s*{re.escape(other)}", description)
        # 两个汉字以上的 id 不太可能是别的词的偶然子串，直接匹配。
        bare = len(other) >= 2 and other in description
        if quoted or named or bare:
            hits.append(other)
    return hits


def validate(profile: Profile, *, check_overlap: bool = True) -> list[Issue]:
    """把 `docs/EVAL.md` 的实测结论变成可执行的检查。

    返回的列表里 ``level == "error"`` 的项必须修掉才能保存；``warning`` 只是提示。
    """
    issues: list[Issue] = []

    def error(field_name: str, message: str) -> None:
        issues.append(Issue("error", field_name, message))

    def warn(field_name: str, message: str) -> None:
        issues.append(Issue("warning", field_name, message))

    # ------------------------------------------------------------ 身份
    if not SLUG_RE.match(profile.id or ""):
        error(
            "id",
            "id 只能用 2~48 位小写字母 / 数字 / 下划线 / 连字符，且以字母或数字开头"
            "（它同时是存盘文件名）",
        )
    if not profile.name:
        error("name", "显示名不能为空")
    elif len(profile.name) > 24:
        warn("name", f"显示名 {len(profile.name)} 个字，页面上会被截断（建议 12 字以内）")

    # ------------------------------------------------------------ 判定问法
    if not profile.criterion:
        error("criterion", "判定问法不能为空 —— 模型读的就是这句话")
    elif len(profile.criterion) > 200:
        warn("criterion", f"判定问法 {len(profile.criterion)} 字偏长，建议压到 200 字以内")
    if any(hint in profile.criterion for hint in RELATIONAL_HINTS):
        warn(
            "criterion",
            "判定问法里出现了「当对方 / 说话人」这类**关系式**说法。"
            "实测：照字面写锚点会全部塌缩到一个选项（八艺上只有 50%）；"
            "改成描述「文本长什么样」才到 96%。",
        )

    # ------------------------------------------------------------ 选项
    if not MIN_LABELS <= len(profile.labels) <= MAX_LABELS:
        error(
            "labels",
            f"选项数量必须在 {MIN_LABELS} 到 {MAX_LABELS} 之间"
            f"（受上游 A–P 单 token 槽位限制），现在是 {len(profile.labels)}",
        )

    seen: set[str] = set()
    duplicates: list[str] = []
    for index, label in enumerate(profile.labels):
        where = f"labels[{index}]"
        label_id = label.get("id", "")
        if not label_id:
            error(where, "选项 id 不能为空")
            continue
        if label_id in seen:
            duplicates.append(label_id)
        seen.add(label_id)
        if len(label_id) > MAX_LABEL_ID:
            warn(where, f"选项 id「{label_id}」超过 {MAX_LABEL_ID} 个字，页面上会挤")
        if re.search(r"\s", label_id):
            error(where, f"选项 id「{label_id}」里有空白字符")

        description = label.get("description", "")
        if not description:
            error(where, f"选项「{label_id}」没有锚点描述 —— 它才是决定判定结果的那段文字")
            continue
        if _quote_count(description) < 2 and "例：" not in description:
            warn(
                where,
                f"选项「{label_id}」的描述里几乎看不到例句。实测：给例句 96% "
                f"vs 只写抽象定义 23% —— 要示范，不要解释。",
            )
        for phrase in GENERIC_PHRASES:
            if phrase in description:
                warn(
                    where,
                    f"选项「{label_id}」的描述里有泛化短语「{phrase}」—— 它几乎对任何文本都成立，"
                    f"会把概率全吸过来（实测删掉这类句子准确率 +7.7 个百分点）。",
                )
        for hint in RELATIONAL_HINTS:
            if hint in description:
                warn(
                    where,
                    f"选项「{label_id}」的描述写成了**关系式**（「{hint}…」）—— "
                    f"要描述「文本长什么样」，不要描述「说话人在干什么」。"
                    f"实测关系式写法在八艺上只有 50%，改成文本形态之后到 96%。",
                )
                break
        for other in _mentions_other_labels(description, label_id, profile.label_ids):
            warn(
                where,
                f"选项「{label_id}」的描述里提到了另一个选项「{other}」—— "
                f"实测这会把概率漏给那个选项，用例句区分，别用名字解释。",
            )
        if not label.get("hint"):
            warn(where, f"选项「{label_id}」没有填「人话提示」，页面上判定结果会少一句解释")

    if duplicates:
        error("labels", f"选项 id 有重复：{'、'.join(sorted(set(duplicates)))}")

    # ------------------------------------------------------------ 示例
    known = profile.labels_by_id()
    if not profile.examples:
        warn("examples", "一条页面示例都没有 —— 用户第一次打开页面会不知道从哪下手")
    example_texts: set[str] = set()
    for index, example in enumerate(profile.examples):
        where = f"examples[{index}]"
        if example["label"] not in known:
            error(where, f"示例指向了不存在的选项「{example['label']}」")
        if example["text"] in example_texts:
            warn(where, "这条示例和前面某条重复")
        example_texts.add(example["text"])
    covered = {example["label"] for example in profile.examples}
    missing = [label_id for label_id in profile.label_ids if label_id not in covered]
    if profile.examples and missing:
        warn("examples", f"这些选项没有页面示例：{'、'.join(missing)}")

    # ------------------------------------------------- 示例 vs 锚点：字面泄漏
    #
    # 这是本项目最贵的一次翻车：测试集抄锚点，测出 96% 的假数字。
    # 页面示例抄锚点同样没有意义 —— 那是自问自答，必对，零信息量。
    if check_overlap:
        descriptions = {label["id"]: label["description"] for label in profile.labels}
        for index, example in enumerate(profile.examples):
            best, who = 0.0, "—"
            for label_id, description in descriptions.items():
                score = overlap(example["text"], description)
                if score > best:
                    best, who = score, label_id
            if best >= LEAK_THRESHOLD:
                warn(
                    f"examples[{index}]",
                    f"这条示例和选项「{who}」的锚点例句字面重合 {best:.2f}（≥ {LEAK_THRESHOLD}）—— "
                    f"等于把 prompt 里的句子拿出来当演示，必对，没有信息量，换一条。",
                )
            elif best >= WARN_THRESHOLD:
                warn(
                    f"examples[{index}]",
                    f"这条示例和选项「{who}」的锚点重合 {best:.2f}，人工看一眼是不是同一句话改了标点。",
                )

    # ------------------------------------------------------------ 长度均衡
    lengths = [len(label.get("description", "")) for label in profile.labels]
    if lengths:
        spread = max(lengths) - min(lengths)
        if spread > LENGTH_SPREAD_SOFT_LIMIT:
            warn(
                "labels",
                f"锚点字数 {min(lengths)}~{max(lengths)}，极差 {spread} 偏大（>{LENGTH_SPREAD_SOFT_LIMIT}）。"
                f"会略微放大位置偏置 —— 但**别为了压这个去删例句**（实测删例句准确率 -8 个百分点）。",
            )

    # ------------------------------------------------------------ 评测状态
    if not profile.evaluated:
        warn(
            "evaluated",
            "这套类型还没有在干净测试集上评测过。页面上的准确率数字是「八艺」的，"
            "不要拿它当这套类型的成绩。",
        )

    return issues


def errors_of(issues: list[Issue]) -> list[Issue]:
    return [issue for issue in issues if issue.level == "error"]


def profile_stats(profile: Profile) -> dict[str, Any]:
    """给编辑器看的几个数字：锚点长度、例句数、prompt 规模。"""
    descriptions = [label.get("description", "") for label in profile.labels]
    quoted = sum(_quote_count(text) for text in descriptions)
    return {
        "label_count": len(profile.labels),
        "example_count": len(profile.examples),
        "description_chars": sum(len(text) for text in descriptions),
        "description_min": min((len(text) for text in descriptions), default=0),
        "description_max": max((len(text) for text in descriptions), default=0),
        "anchor_examples": quoted,
        "criterion_chars": len(profile.criterion),
        # 锚点进 prompt，所以它直接决定每次判定的输入长度（也是延迟的主因）。
        "prompt_chars": sum(len(text) for text in descriptions) + len(profile.criterion),
    }


# --------------------------------------------------------------------- 存储


class ProfileError(ValueError):
    """保存 / 导入被拒。``issues`` 里是具体原因，页面直接摊开给用户看。"""

    def __init__(self, message: str, issues: list[Issue] | None = None) -> None:
        super().__init__(message)
        self.issues = issues or []


class ProfileStore:
    """内置类型（代码里）+ 用户类型（``data/profiles/*.json``）。

    内置的只读：想改就「另存为」一份新的。这样升级时不会被用户改过的
    内置锚点悄悄顶掉，评测数字也永远对应得到一份确定的锚点。
    """

    def __init__(self, user_dir: Path | None = None, builtin_dir: Path | None = None) -> None:
        self.user_dir = Path(user_dir) if user_dir else USER_DIR
        self.builtin_dir = Path(builtin_dir) if builtin_dir else BUILTIN_DIR

    # ------------------------------------------------------------ 内置

    def _builtin_profiles(self) -> list[Profile]:
        profiles = [self._bayi_profile()]
        if self.builtin_dir.is_dir():
            for path in sorted(self.builtin_dir.glob("*.json")):
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                profile = Profile.from_dict(raw)
                profile.builtin = True
                profiles.append(profile)
        return profiles

    @staticmethod
    def _bayi_profile() -> Profile:
        """「八艺」的出处仍然是 ``biaochi/labels.py`` —— 它是唯一权威。"""
        return Profile(
            id=DEFAULT_PROFILE_ID,
            name="八艺",
            summary="八个字：典 孝 急 乐 蚌 批 赢 麻 —— 这条评论该回哪个字",
            criterion=CRITERION,
            labels=[dict(label) for label in MEME_LABELS],
            examples=[dict(example) for example in EXAMPLES],
            version="meme-direct-zh-v4",
            note="项目自带的默认类型，是唯一在干净测试集上评测过的类型。",
            builtin=True,
            evaluated=True,
        )

    # ------------------------------------------------------------ 用户

    def _user_paths(self) -> dict[str, Path]:
        if not self.user_dir.is_dir():
            return {}
        return {path.stem: path for path in sorted(self.user_dir.glob("*.json"))}

    def _load_user(self, path: Path) -> Profile | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        profile = Profile.from_dict(raw)
        profile.builtin = False
        # **文件名就是 id。** 手写的 JSON 里 id 和文件名不一致时以文件名为准 ——
        # 因为 save / delete / export 全都按文件名找，两边不一致会变成
        # 「删不掉」和「列表里出现两个同 id 的条目」这种查半天的问题。
        profile.id = path.stem
        return profile

    # ------------------------------------------------------------ 读

    def list(self) -> list[Profile]:
        """内置在前、用户在后；同 id 时用户版**不会**覆盖内置版（内置只读）。"""
        profiles = self._builtin_profiles()
        taken = {profile.id for profile in profiles}
        for profile_id, path in self._user_paths().items():
            if profile_id in taken:
                continue
            profile = self._load_user(path)
            if profile is not None:
                profiles.append(profile)
                taken.add(profile.id)
        return profiles

    def get(self, profile_id: str) -> Profile | None:
        for profile in self.list():
            if profile.id == profile_id:
                return profile
        return None

    def exists(self, profile_id: str) -> bool:
        return self.get(profile_id) is not None

    def path_of(self, profile_id: str) -> Path:
        return self.user_dir / f"{profile_id}.json"

    # ------------------------------------------------------------ 写

    def save(self, profile: Profile, *, overwrite: bool = False) -> Profile:
        """保存一套用户类型。内置类型只读，想改就先另存为一份。"""
        # 存下来的一定是用户类型：导出的内置类型里带着 builtin=true，
        # 那份文件再被导入时这个标记必须丢掉，否则「导入内置类型的副本」永远失败。
        profile.builtin = False
        issues = validate(profile)
        blocking = errors_of(issues)
        if blocking:
            raise ProfileError(
                "校验没通过：" + "；".join(issue.message for issue in blocking), blocking
            )
        if profile.id == DEFAULT_PROFILE_ID:
            raise ProfileError(
                f"{DEFAULT_PROFILE_ID} 是内置类型的 id（它永远在，只读），换一个，比如 bayi-2",
                [Issue("error", "id", f"{DEFAULT_PROFILE_ID} 是内置类型")],
            )
        target = self.path_of(profile.id)
        if target.exists() and not overwrite:
            raise ProfileError(
                f"已经存在同 id 的类型「{profile.id}」，确认要覆盖再重试。",
                [Issue("error", "id", "同 id 已存在")],
            )
        profile.updated_at = _now()
        self.user_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(profile.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return profile

    def delete(self, profile_id: str) -> bool:
        """只删用户类型。内置的删不掉 —— 那是仓库的一部分。"""
        path = self._user_paths().get(profile_id)
        if path is None:
            return False
        path.unlink()
        return True

    # ------------------------------------------------------------ 导入导出

    def export_dict(self, profile_id: str) -> dict[str, Any]:
        profile = self.get(profile_id)
        if profile is None:
            raise ProfileError(f"没有这个判断类型：{profile_id}")
        return profile.to_dict()

    def import_dict(self, raw: dict[str, Any], *, overwrite: bool = False) -> Profile:
        """从导出文件 / 手写 JSON 导入。id 撞车时报错，除非显式 overwrite。"""
        profile = Profile.from_dict(raw)
        if not profile.id:
            raise ProfileError("导入的文件里没有 id")
        return self.save(profile, overwrite=overwrite)


__all__ = [
    "DEFAULT_PROFILE_ID",
    "GENERIC_PHRASES",
    "Issue",
    "LENGTH_SPREAD_SOFT_LIMIT",
    "MAX_LABELS",
    "MAX_LABEL_ID",
    "MIN_LABELS",
    "Profile",
    "ProfileError",
    "ProfileStore",
    "SLUG_RE",
    "USER_DIR",
    "errors_of",
    "profile_stats",
    "validate",
]
