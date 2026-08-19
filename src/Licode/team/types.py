"""Agent Team 的基础数据类型。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class BackendType(StrEnum):
    TMUX = "tmux"
    ITERM2 = "iterm2"
    IN_PROCESS = "in-process"


class TeamError(RuntimeError):
    """Team 子系统可由调用方识别的基础错误。"""


class TeamNotFoundError(TeamError):
    pass


class TeamHasActiveMembersError(TeamError):
    pass


class MemberExistsError(TeamError):
    pass


class MemberNotFoundError(TeamError):
    pass


class InProcessTeammateNoSpawnError(TeamError):
    pass


@dataclass
class TeammateInfo:
    name: str
    agent_id: str
    agent_type: str = ""
    model: str = ""
    worktree_path: str = ""
    branch: str = ""
    backend_type: BackendType = BackendType.IN_PROCESS
    pane_id: str = ""
    is_active: bool | None = None
    plan_mode_required: bool = False
    session_dir: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "agent_id": self.agent_id,
            "agent_type": self.agent_type,
            "model": self.model,
            "worktree_path": self.worktree_path,
            "branch": self.branch,
            "backend_type": self.backend_type.value,
            "pane_id": self.pane_id,
            "is_active": self.is_active,
            "plan_mode_required": self.plan_mode_required,
            "session_dir": self.session_dir,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> TeammateInfo:
        active = value.get("is_active")
        if active is not None and not isinstance(active, bool):
            raise ValueError("is_active 必须是布尔值或 null")
        backend_raw = value.get("backend_type", BackendType.IN_PROCESS.value)
        if not isinstance(backend_raw, str):
            raise ValueError("backend_type 必须是字符串")
        return cls(
            name=_required_string(value, "name"),
            agent_id=_required_string(value, "agent_id"),
            agent_type=_optional_string(value, "agent_type"),
            model=_optional_string(value, "model"),
            worktree_path=_optional_string(value, "worktree_path"),
            branch=_optional_string(value, "branch"),
            backend_type=BackendType(backend_raw),
            pane_id=_optional_string(value, "pane_id"),
            is_active=active,
            plan_mode_required=_optional_bool(value, "plan_mode_required"),
            session_dir=_optional_string(value, "session_dir"),
        )


@dataclass
class Team:
    name: str
    sanitized_name: str
    lead_agent_id: str
    backend: BackendType
    description: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    members: list[TeammateInfo] = field(default_factory=list)
    config_dir: str = ""
    config_path: str = ""
    tasks_path: str = ""
    mailbox_dir: str = ""
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False, compare=False)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "sanitized_name": self.sanitized_name,
            "lead_agent_id": self.lead_agent_id,
            "backend": self.backend.value,
            "description": self.description,
            "created_at": int(self.created_at.timestamp()),
            "members": [member.to_dict() for member in self.members],
        }

    def member_by_name(self, name: str) -> TeammateInfo | None:
        return next((member for member in self.members if member.name == name), None)

    def member_by_agent_id(self, agent_id: str) -> TeammateInfo | None:
        return next((member for member in self.members if member.agent_id == agent_id), None)

    async def add_member(self, info: TeammateInfo) -> None:
        from .persistence import atomic_write_json, reload_from_disk_locked

        async with self._lock:
            # Pane 队员与 Lead 分属不同进程，修改前必须先合并磁盘上的最新花名册。
            await reload_from_disk_locked(self)
            if self.member_by_name(info.name) is not None:
                raise MemberExistsError(f"Team 成员已存在: {info.name}")
            self.members.append(info)
            atomic_write_json(self.config_path, self.to_dict())

    async def set_member_active(self, name: str, active: bool) -> None:
        from .persistence import atomic_write_json, reload_from_disk_locked

        async with self._lock:
            await reload_from_disk_locked(self)
            member = self.member_by_name(name)
            if member is None:
                raise MemberNotFoundError(f"Team 成员不存在: {name}")
            member.is_active = active
            atomic_write_json(self.config_path, self.to_dict())

    async def remove_member(self, name: str) -> None:
        from .persistence import atomic_write_json, reload_from_disk_locked

        async with self._lock:
            await reload_from_disk_locked(self)
            member = self.member_by_name(name)
            if member is None:
                raise MemberNotFoundError(f"Team 成员不存在: {name}")
            self.members = [item for item in self.members if item.name != name]
            atomic_write_json(self.config_path, self.to_dict())


def _required_string(value: dict[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{key} 必须是非空字符串")
    return item


def _optional_string(value: dict[str, object], key: str) -> str:
    item = value.get(key, "")
    if not isinstance(item, str):
        raise ValueError(f"{key} 必须是字符串")
    return item


def _optional_bool(value: dict[str, object], key: str) -> bool:
    item = value.get(key, False)
    if not isinstance(item, bool):
        raise ValueError(f"{key} 必须是布尔值")
    return item
