"""跨多轮 Agent.run 复用的会话状态。"""

import asyncio
from dataclasses import dataclass, field

from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    SessionContext,
)
from Licode.skills.active import ActiveSkills


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
    active_skills: ActiveSkills = field(default_factory=ActiveSkills)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def reset_for_new_session(self, session: SessionContext) -> None:
        """保留模型窗口配置，并重置所有会话级状态。"""

        self.replacement = ContentReplacementState()
        self.recovery = RecoveryState()
        self.auto_tracking = CompactCircuitBreaker()
        self.session = session
        self.turn_count = 0
        self.usage_anchor = 0
        self.anchor_msg_len = 0
        self.active_skills.clear()
