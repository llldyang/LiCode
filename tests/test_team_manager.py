from __future__ import annotations

import json
from pathlib import Path

import pytest

from Licode.team import (
    AgentNameRegistry,
    BackendType,
    Manager,
    TeamHasActiveMembersError,
    TeammateInfo,
)
from Licode.tui.team_adapter import TeamAdapter


class FakeTaskManager:
    def __init__(self) -> None:
        self.stopped: list[str] = []

    async def stop(self, task_id: str) -> bool:
        self.stopped.append(task_id)
        return True


class FakeWorktreeManager:
    def __init__(self) -> None:
        self.removed: list[str] = []

    async def remove(self, name: str, options) -> None:
        del options
        self.removed.append(name)


@pytest.mark.asyncio
async def test_create_sanitize_duplicate_and_restore(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("Licode.team.manager.detect", lambda: BackendType.IN_PROCESS)
    registry = AgentNameRegistry()
    manager = Manager(tmp_path, tmp_path, None, FakeTaskManager(), registry)  # type: ignore[arg-type]

    first = await manager.create("foo bar/baz", "测试团队")
    second = await manager.create("foo bar/baz", "")

    assert first.sanitized_name == "foo-bar-baz"
    assert second.sanitized_name == "foo-bar-baz-2"
    assert Path(first.config_path).is_file()
    restored = Manager(tmp_path, tmp_path, None, FakeTaskManager(), registry)  # type: ignore[arg-type]
    assert set(restored.teams) == {"foo-bar-baz", "foo-bar-baz-2"}


@pytest.mark.asyncio
async def test_delete_requires_force_while_lead_active(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("Licode.team.manager.detect", lambda: BackendType.IN_PROCESS)
    manager = Manager(  # type: ignore[arg-type]
        tmp_path, tmp_path, None, FakeTaskManager(), AgentNameRegistry()
    )
    team = await manager.create("demo", "")

    with pytest.raises(TeamHasActiveMembersError):
        await manager.delete("demo", False)
    assert Path(team.config_dir).is_dir()

    await manager.delete("demo", True)
    assert not Path(team.config_dir).exists()


@pytest.mark.asyncio
async def test_member_update_reloads_disk_before_modify(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("Licode.team.manager.detect", lambda: BackendType.IN_PROCESS)
    manager = Manager(  # type: ignore[arg-type]
        tmp_path, tmp_path, None, FakeTaskManager(), AgentNameRegistry()
    )
    team = await manager.create("demo", "")
    disk = json.loads(Path(team.config_path).read_text(encoding="utf-8"))
    disk["members"].append(TeammateInfo(name="alice", agent_id="agent-1", is_active=True).to_dict())
    Path(team.config_path).write_text(json.dumps(disk), encoding="utf-8")

    await team.set_member_active("alice", False)

    persisted = json.loads(Path(team.config_path).read_text(encoding="utf-8"))
    alice = next(item for item in persisted["members"] if item["name"] == "alice")
    assert alice["is_active"] is False


@pytest.mark.asyncio
async def test_team_kill_cleans_member_resources_before_removing_roster_entry(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("Licode.team.manager.detect", lambda: BackendType.IN_PROCESS)
    task_manager = FakeTaskManager()
    worktree_manager = FakeWorktreeManager()
    manager = Manager(  # type: ignore[arg-type]
        tmp_path,
        tmp_path,
        worktree_manager,
        task_manager,
        AgentNameRegistry(),
    )
    team = await manager.create("demo", "")
    session_dir = tmp_path / "session-alice"
    session_dir.mkdir()
    await team.add_member(
        TeammateInfo(
            name="alice",
            agent_id="agent-1",
            worktree_path=str(tmp_path / "worktree-alice"),
            backend_type=BackendType.IN_PROCESS,
            is_active=True,
            session_dir=str(session_dir),
        )
    )

    await TeamAdapter(manager).kill("alice")

    assert task_manager.stopped == ["agent-1"]
    assert worktree_manager.removed == ["team-demo/alice"]
    assert not session_dir.exists()
    assert team.member_by_name("alice") is None
