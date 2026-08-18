"""Agent 向终端界面投递的事件类型。"""

from dataclasses import dataclass
from enum import Enum, IntEnum


class Phase(IntEnum):
    START = 0
    END = 1


@dataclass
class Usage:
    """一轮请求的 token 用量与缓存命中信息。"""

    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0


@dataclass
class ToolEvent:
    """供界面渲染的一次工具开始或结束事件。"""

    name: str
    args: str = ""
    phase: Phase = Phase.START
    result: str = ""
    is_error: bool = False


class CompactPhase(Enum):
    BEFORE_AUTO = "before_auto"
    AFTER_AUTO = "after_auto"
    BEFORE_EMERGENCY = "before_emergency"
    AFTER_EMERGENCY = "after_emergency"


@dataclass
class CompactEvent:
    phase: CompactPhase
    before: int = 0
    after: int = 0
    err: Exception | None = None


@dataclass
class Event:
    """Agent Loop 向界面输出的统一事件。"""

    text: str = ""
    tool: ToolEvent | None = None
    usage: Usage | None = None
    iter: int = 0
    notice: str = ""
    done: bool = False
    err: Exception | None = None
    compact: CompactEvent | None = None
