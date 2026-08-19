from __future__ import annotations

import os
import re
import time
from pathlib import Path

import pytest

from Licode.team.tasks import Filter, Patch, Status, Store, Task


@pytest.mark.asyncio
async def test_task_store_dependencies_and_readiness(tmp_path: Path) -> None:
    store = Store(str(tmp_path / "tasks.json"))
    blocker_id = await store.create(Task(title="基础任务"))
    blocked_id = await store.create(Task(title="后续任务"))
    assert re.fullmatch(r"task_[0-9a-f]{6}", blocker_id)

    await store.update(blocked_id, Patch(add_blocked_by=[blocker_id]))
    blocker = await store.get(blocker_id)
    blocked = await store.get(blocked_id)
    assert blocked.blocked_by == [blocker_id]
    assert blocker.blocks == [blocked_id]
    assert (await store.list_(Filter(status=Status.PENDING)))[1].is_ready is False

    await store.update(blocker_id, Patch(status=Status.COMPLETED))
    pending = await store.list_(Filter(status=Status.PENDING))
    assert next(task for task in pending if task.id == blocked_id).is_ready is True


@pytest.mark.asyncio
async def test_task_remove_dependency_updates_both_sides(tmp_path: Path) -> None:
    store = Store(str(tmp_path / "tasks.json"))
    first = await store.create(Task(title="一"))
    second = await store.create(Task(title="二"))
    await store.update(second, Patch(add_blocked_by=[first]))
    await store.update(second, Patch(remove_blocked_by=[first]))
    assert (await store.get(second)).blocked_by == []
    assert (await store.get(first)).blocks == []


@pytest.mark.asyncio
async def test_task_store_uses_documented_tasks_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "tasks.lock"
    lock_path.write_text("stale", encoding="utf-8")
    old = time.time() - 11
    os.utime(lock_path, (old, old))

    await Store(str(tmp_path / "tasks.json")).create(Task(title="使用规范锁文件"))

    assert not lock_path.exists()
    assert not (tmp_path / "tasks.json.lock").exists()
