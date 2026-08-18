"""跨多轮 Agent.run 复用的会话状态。"""

import asyncio
from dataclasses import dataclass, field

from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    SessionContext,
)


@dataclass
class SessionRuntime:
    replacement: ContentReplacementState
    recovery: RecoveryState
    auto_tracking: CompactCircuitBreaker
    session: SessionContext
    context_window: int = 200000
    turn_count: int = 0
    usage_anchor: int = 0
    anchor_msg_len: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
