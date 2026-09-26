"""八艺 —— 用开源版 Jev（SemIf）判定这条评论该回哪个字。"""

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
]
