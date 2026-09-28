"""八艺 —— 用独立开源实现 SemIf（复现 Jev 提出的「决策模型」接口形态）判定这条评论该回哪个字。

判定逻辑（词表 / 判定问法 / 示例）是**运行时的数据**，不是训练出来的参数：
想换一套判断类型，换一个 ``Profile``，不用动模型，更不用重训。
"""

from .engine import (
    DEFAULT_MODEL_DIR,
    DEFAULT_PERMUTATIONS,
    DEFAULT_REVISION,
    MODEL_CHOICES,
    MemeJev,
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
    "MemeJev",
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
