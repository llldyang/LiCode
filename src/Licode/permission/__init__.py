"""权限模式、裁决类型与权限引擎门面。"""

from enum import IntEnum


class Mode(IntEnum):
    DEFAULT = 0
    ACCEPT_EDITS = 1
    PLAN = 2
    BYPASS = 3

    def __str__(self) -> str:
        return {
            Mode.DEFAULT: "default",
            Mode.ACCEPT_EDITS: "acceptEdits",
            Mode.PLAN: "plan",
            Mode.BYPASS: "bypassPermissions",
        }[self]


def parse_mode(value: str) -> tuple[Mode, bool]:
    """大小写不敏感地解析四档权限模式。"""

    normalized = value.strip().lower()
    for mode in Mode:
        if normalized == str(mode).lower():
            return mode, True
    return Mode.DEFAULT, False


class Decision(IntEnum):
    ALLOW = 0
    DENY = 1
    ASK = 2


class Category(IntEnum):
    READ = 0
    WRITE = 1
    EXEC = 2


class Outcome(IntEnum):
    DENY_ONCE = 0
    ALLOW_ONCE = 1
    ALLOW_FOREVER = 2


class ApprovalError(Exception):
    """权限审批或规则持久化失败。"""


from .engine import Engine, mode_fallback, new_engine, start_mode  # noqa: E402
from .matcher import (  # noqa: E402
    ExactMatcher,
    GlobMatcher,
    Matcher,
    NotMatcher,
    RegexMatcher,
    compile_matcher,
)
from .persist import persist_local_allow  # noqa: E402

__all__ = [
    "ApprovalError",
    "Category",
    "Decision",
    "Engine",
    "ExactMatcher",
    "GlobMatcher",
    "Matcher",
    "Mode",
    "Outcome",
    "NotMatcher",
    "RegexMatcher",
    "compile_matcher",
    "mode_fallback",
    "new_engine",
    "parse_mode",
    "persist_local_allow",
    "start_mode",
]
