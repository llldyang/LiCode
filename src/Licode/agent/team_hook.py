"""Agent 与 Team 子系统之间的无环上下文协议。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from Licode.team.types import BackendType


@dataclass
class IncomingMessage:
    from_: str
    type: str
    summary: str
    content: str
    timestamp: int
    payload: dict[str, object] | None = None


@dataclass
class TeammateContext:
    team_name: str
    member_name: str
    agent_id: str
    backend_type: BackendType
    mailbox_dir: str
    read_unread: Callable[[], Awaitable[tuple[list[int], list[IncomingMessage]]]]
    mark_read: Callable[[list[int]], Awaitable[None]]


@dataclass
class TeamSpawnRequest:
    team_name: str
    member_name: str
    prompt: str
    description: str
    subagent_type: str = ""
    model: str = ""
    plan_mode_required: bool = False


class TeamHook(Protocol):
    async def spawn_teammate(self, request: TeamSpawnRequest) -> str: ...

    def is_teammate_context(self) -> tuple[str, str, bool]: ...


def teammate_context_from_ctx() -> TeammateContext | None:
    from .context import current_agent

    agent = current_agent()
    return agent.team_context if agent is not None else None


__all__ = [
    "IncomingMessage",
    "TeamHook",
    "TeamSpawnRequest",
    "TeammateContext",
    "teammate_context_from_ctx",
]
