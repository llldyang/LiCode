import asyncio
import os
import subprocess
from pathlib import Path

import pytest

from Licode.worktree import (
    ExitAction,
    ExitOptions,
    Manager,
    WorktreeHasChangesError,
)


def init_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / ".gitignore").write_text(
        ".Licode/worktrees/\n.Licode/worktree_session.json\n", encoding="utf-8"
    )
    (path / "tracked.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


@pytest.mark.asyncio
async def test_enter_exit_protects_changes_and_restores_cwd(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    manager = Manager(str(repo))
    wt = await manager.create("alice", "HEAD", manual=True)
    original = Path.cwd()
    session = await manager.enter("alice")
    assert Path.cwd() == original
    assert session.worktree_path == wt.path
    assert session.session_id
    assert Path(manager.session_file).read_text(encoding="utf-8") != "null"
    (Path(wt.path) / "tracked.txt").write_text("changed\n", encoding="utf-8")

    with pytest.raises(WorktreeHasChangesError):
        await manager.exit("alice", ExitAction.REMOVE, ExitOptions())
    assert Path(wt.path).exists()

    os.chdir(wt.path)
    try:
        report = await manager.exit("alice", ExitAction.REMOVE, ExitOptions(discard_changes=True))
    finally:
        os.chdir(original)
    assert report.removed
    assert not Path(wt.path).exists()
    assert Path(manager.session_file).read_text(encoding="utf-8") == "null"
    assert Path.cwd() == original


@pytest.mark.asyncio
async def test_remove_non_current_and_auto_cleanup(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    manager = Manager(str(repo))
    manual = await manager.create("manual", "HEAD", manual=True)
    kept = await manager.auto_cleanup("manual")
    assert kept.kept and kept.path == manual.path
    await manager.remove("manual", ExitOptions(discard_changes=True))

    temporary = await manager.create("agent-a1234567", "HEAD", manual=False)
    cleaned = await manager.auto_cleanup(temporary.name)
    assert not cleaned.kept
    assert not Path(temporary.path).exists()


@pytest.mark.asyncio
async def test_auto_cleanup_keeps_modified_temporary_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    manager = Manager(str(repo))
    wt = await manager.create("agent-a7654321", "HEAD", manual=False)
    (Path(wt.path) / "new.txt").write_text("change\n", encoding="utf-8")
    report = await manager.auto_cleanup(wt.name)
    assert report.kept and report.branch == wt.branch
    assert Path(wt.path).exists()


@pytest.mark.asyncio
async def test_restored_manager_keeps_creation_baseline_for_commit_protection(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    manager = Manager(str(repo))
    wt = await manager.create("alice", "HEAD", manual=True)
    creation_head = wt.head_commit
    (Path(wt.path) / "tracked.txt").write_text("committed\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=wt.path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "changed"], cwd=wt.path, check=True)

    restored_manager = Manager(str(repo))
    restored = restored_manager.get("alice")
    assert restored is not None
    assert restored.head_commit == creation_head
    with pytest.raises(WorktreeHasChangesError):
        await restored_manager.remove("alice", ExitOptions())
    await restored_manager.remove("alice", ExitOptions(discard_changes=True))


@pytest.mark.asyncio
async def test_same_worktree_lifecycle_operations_are_mutually_exclusive(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    manager = Manager(str(repo))
    await manager.create("alice", "HEAD", manual=False)
    started = asyncio.Event()
    proceed = asyncio.Event()

    async def blocked_change_check(_path, _base):
        started.set()
        await proceed.wait()
        return False

    monkeypatch.setattr("Licode.worktree.lifecycle._has_worktree_changes", blocked_change_check)
    removing = asyncio.create_task(manager.remove("alice", ExitOptions()))
    await started.wait()
    with pytest.raises(RuntimeError, match="正在执行其他操作"):
        await manager.auto_cleanup("alice")
    proceed.set()
    await removing
