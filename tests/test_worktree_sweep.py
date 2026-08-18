import os
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from Licode.worktree import Manager, Worktree, random_agent_name


def init_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / ".gitignore").write_text(
        ".Licode/worktrees/\n.Licode/worktree_session.json\n", encoding="utf-8"
    )
    subprocess.run(["git", "add", ".gitignore"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


def test_random_agent_name_matches_cleanup_pattern() -> None:
    assert re.fullmatch(r"agent-a[0-9a-f]{7}", random_agent_name())


@pytest.mark.asyncio
async def test_sweep_uses_name_time_session_and_change_filters(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    manager = Manager(str(repo))
    root = Path(manager.worktree_dir)
    names = ["agent-a1111111", "agent-a2222222", "agent-a3333333", "manual"]
    old = datetime.now() - timedelta(days=2)
    for name in names:
        path = root / name
        path.mkdir()
        os.utime(path, (old.timestamp(), old.timestamp()))
        manager.active[name] = Worktree(
            name, str(path), f"worktree-{name}", "base", "base", old, name == "manual"
        )

    manager._current_session = type(
        "Session", (), {"worktree_path": str(root / "agent-a2222222")}
    )()

    async def has_changes(path, _base):
        return Path(path).name == "agent-a3333333"

    async def run_git(*_args):
        return ""

    async def remove(name, _opts):
        manager.active.pop(name)

    monkeypatch.setattr("Licode.worktree.sweep._has_worktree_changes", has_changes)
    monkeypatch.setattr("Licode.worktree.sweep._run_git", run_git)
    monkeypatch.setattr(manager, "remove", remove)

    removed = await manager.sweep_stale(datetime.now() - timedelta(days=1))
    assert removed == ["agent-a1111111"]
    assert set(manager.active) == {"agent-a2222222", "agent-a3333333", "manual"}
