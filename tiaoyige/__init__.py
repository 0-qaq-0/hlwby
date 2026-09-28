"""帮你挑一个 —— 用独立开源实现 SemIf（复现 Jev 提出的「决策模型」接口形态）判定这条评论该回哪个字。

判定逻辑（词表 / 判定问法 / 示例）是**运行时的数据**，不是训练出来的参数：
想换一套判断类型，换一个 ``Profile``，不用动模型，更不用重训。
"""

from .console import enable_utf8 as _enable_utf8

# 这个包是**应用**不是库，所以 import 时就把中文输出修好：
# 英文 Windows 上往管道里 print 中文会直接 UnicodeEncodeError 崩掉
# （release 工作流在 windows-latest 上就是这么红的）。见 tiaoyige/console.py。
# 不 import 本包的独立脚本（scripts/build_release.py）自己显式调一次。
_enable_utf8()

from .engine import (
    DEFAULT_MODEL_DIR,
    DEFAULT_PERMUTATIONS,
    DEFAULT_REVISION,
    MODEL_CHOICES,
    Tiaoyige,
    permutations_of,
    pick_device,
)
from .labels import (
    CRITERION,
    EXAMPLES,
    LABEL_IDS,
    LABELS_BY_ID,
    MEME_LABELS,
)
from .profiles import (
    DEFAULT_PROFILE_ID,
    Issue,
    Profile,
    ProfileError,
    ProfileStore,
    profile_stats,
    validate,
)
from .version import __version__

__all__ = [
    "Tiaoyige",
    "MEME_LABELS",
    "LABEL_IDS",
    "LABELS_BY_ID",
    "CRITERION",
    "EXAMPLES",
    "DEFAULT_MODEL_DIR",
    "DEFAULT_REVISION",
    "DEFAULT_PERMUTATIONS",
    "MODEL_CHOICES",
    "permutations_of",
    "pick_device",
    "Profile",
    "ProfileStore",
    "ProfileError",
    "Issue",
    "DEFAULT_PROFILE_ID",
    "validate",
    "profile_stats",
    "__version__",
]
