"""跨多轮 Agent.run 复用的会话状态。"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    SessionContext,
)
from Licode.skills.active import ActiveSkills

if TYPE_CHECKING:
    from Licode.hook import Engine as HookEngine


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
    pending_reminders: list[str] = field(default_factory=list)
    hook_engine: HookEngine | None = None
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _reminder_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def append_reminders(self, prompts: list[str]) -> None:
        with self._reminder_lock:
            self.pending_reminders.extend(prompts)

    def take_reminders(self) -> list[str]:
        with self._reminder_lock:
            result = list(self.pending_reminders)
            self.pending_reminders.clear()
        return result

    async def reset_for_new_session(self, session: SessionContext) -> None:
        """保留模型窗口配置，并重置所有会话级状态。"""

        previous_session_id = self.session.session_id
        self.replacement = ContentReplacementState()
        self.recovery = RecoveryState()
        self.auto_tracking = CompactCircuitBreaker()
        self.session = session
        self.turn_count = 0
        self.usage_anchor = 0
        self.anchor_msg_len = 0
        self.active_skills.clear()
        with self._reminder_lock:
            self.pending_reminders.clear()
        if self.hook_engine is not None:
            await self.hook_engine.reset_for_new_session(previous_session_id)
