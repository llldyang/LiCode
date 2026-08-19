"""Team 共享任务列表及依赖图。"""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from Licode.team.filelock import acquire
from Licode.team.persistence import atomic_write_json, read_json


class Status(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass
class Task:
    id: str = ""
    title: str = ""
    description: str = ""
    status: Status = Status.PENDING
    assignee: str = ""
    blocked_by: list[str] = field(default_factory=list)
    blocks: list[str] = field(default_factory=list)
    created_at: int = 0
    updated_at: int = 0
    is_ready: bool = True

    def to_dict(self, *, include_ready: bool = False) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status.value,
            "assignee": self.assignee,
            "blocked_by": list(self.blocked_by),
            "blocks": list(self.blocks),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if include_ready:
            value["is_ready"] = self.is_ready
        return value

    @classmethod
    def from_dict(cls, value: object) -> Task:
        if not isinstance(value, dict):
            raise ValueError("共享任务必须是 JSON 对象")
        return cls(
            id=_text(value, "id"),
            title=_text(value, "title"),
            description=_text(value, "description", allow_empty=True),
            status=Status(value.get("status", Status.PENDING.value)),
            assignee=_text(value, "assignee", allow_empty=True),
            blocked_by=_string_list(value, "blocked_by"),
            blocks=_string_list(value, "blocks"),
            created_at=_integer(value, "created_at"),
            updated_at=_integer(value, "updated_at"),
        )


@dataclass
class Filter:
    status: Status | None = None


@dataclass
class Patch:
    title: str | None = None
    description: str | None = None
    status: Status | None = None
    assignee: str | None = None
    add_blocks: list[str] = field(default_factory=list)
    add_blocked_by: list[str] = field(default_factory=list)
    remove_blocks: list[str] = field(default_factory=list)
    remove_blocked_by: list[str] = field(default_factory=list)


class Store:
    def __init__(self, path: str) -> None:
        self._path = str(Path(path).resolve())
        self._lock_path = str(Path(self._path).with_suffix(".lock"))
        self._lock = asyncio.Lock()

    def _read_unlocked(self) -> list[Task]:
        try:
            value = read_json(self._path)
        except FileNotFoundError:
            return []
        if not isinstance(value, dict) or not isinstance(value.get("tasks"), list):
            raise ValueError("tasks.json 格式无效")
        return [Task.from_dict(item) for item in value["tasks"]]

    def _write_unlocked(self, tasks: list[Task]) -> None:
        atomic_write_json(self._path, {"tasks": [task.to_dict() for task in tasks]})

    async def create(self, task: Task) -> str:
        async with self._lock, acquire(self._lock_path):
            tasks = self._read_unlocked()
            task.id = task.id or f"task_{secrets.token_hex(3)}"
            if any(item.id == task.id for item in tasks):
                raise ValueError(f"任务已存在: {task.id}")
            now = int(time.time())
            task.created_at = task.created_at or now
            task.updated_at = now
            known = {item.id: item for item in tasks}
            for blocker_id in task.blocked_by:
                blocker = known.get(blocker_id)
                if blocker is None:
                    raise KeyError(f"依赖任务不存在: {blocker_id}")
                _append_unique(blocker.blocks, task.id)
                blocker.updated_at = now
            tasks.append(task)
            self._write_unlocked(tasks)
            return task.id

    async def get(self, id_: str) -> Task:
        async with self._lock, acquire(self._lock_path):
            task = next((item for item in self._read_unlocked() if item.id == id_), None)
            if task is None:
                raise KeyError(f"任务不存在: {id_}")
            return task

    async def list_(self, filter_: Filter | None = None) -> list[Task]:
        async with self._lock, acquire(self._lock_path):
            tasks = self._read_unlocked()
        by_id = {task.id: task for task in tasks}
        result: list[Task] = []
        for task in tasks:
            if filter_ is not None and filter_.status is not None and task.status != filter_.status:
                continue
            ready = all(
                by_id.get(blocker) is not None and by_id[blocker].status is Status.COMPLETED
                for blocker in task.blocked_by
            )
            result.append(replace(task, is_ready=ready))
        return result

    async def update(self, id_: str, patch: Patch) -> None:
        async with self._lock, acquire(self._lock_path):
            tasks = self._read_unlocked()
            by_id = {task.id: task for task in tasks}
            task = by_id.get(id_)
            if task is None:
                raise KeyError(f"任务不存在: {id_}")
            if patch.title is not None:
                task.title = patch.title
            if patch.description is not None:
                task.description = patch.description
            if patch.status is not None:
                task.status = patch.status
            if patch.assignee is not None:
                task.assignee = patch.assignee

            for related_id in (*patch.add_blocks, *patch.add_blocked_by):
                if related_id not in by_id:
                    raise KeyError(f"关联任务不存在: {related_id}")
                if related_id == id_:
                    raise ValueError("任务不能依赖自身")

            for target_id in patch.add_blocks:
                _append_unique(task.blocks, target_id)
                _append_unique(by_id[target_id].blocked_by, id_)
            for blocker_id in patch.add_blocked_by:
                _append_unique(task.blocked_by, blocker_id)
                _append_unique(by_id[blocker_id].blocks, id_)
            for target_id in patch.remove_blocks:
                _remove(task.blocks, target_id)
                if target_id in by_id:
                    _remove(by_id[target_id].blocked_by, id_)
            for blocker_id in patch.remove_blocked_by:
                _remove(task.blocked_by, blocker_id)
                if blocker_id in by_id:
                    _remove(by_id[blocker_id].blocks, id_)

            now = int(time.time())
            touched = {id_, *patch.add_blocks, *patch.add_blocked_by}
            touched.update(patch.remove_blocks)
            touched.update(patch.remove_blocked_by)
            for touched_id in touched:
                if touched_id in by_id:
                    by_id[touched_id].updated_at = now
            self._write_unlocked(tasks)


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _remove(values: list[str], value: str) -> None:
    if value in values:
        values.remove(value)


def _text(value: dict[str, Any], key: str, *, allow_empty: bool = False) -> str:
    item = value.get(key, "")
    if not isinstance(item, str) or (not allow_empty and not item):
        raise ValueError(f"{key} 必须是字符串")
    return item


def _string_list(value: dict[str, Any], key: str) -> list[str]:
    item = value.get(key, [])
    if not isinstance(item, list) or any(not isinstance(entry, str) for entry in item):
        raise ValueError(f"{key} 必须是字符串数组")
    return list(dict.fromkeys(item))


def _integer(value: dict[str, Any], key: str) -> int:
    item = value.get(key, 0)
    if isinstance(item, bool) or not isinstance(item, int):
        raise ValueError(f"{key} 必须是整数")
    return item


__all__ = ["Filter", "Patch", "Status", "Store", "Task"]
