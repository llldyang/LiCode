import os
import subprocess
from pathlib import Path

import pytest

from Licode.worktree import Manager


def init_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / ".gitignore").write_text(
        ".env\n.Licode/worktrees/\n.Licode/worktree_session.json\n", encoding="utf-8"
    )
    (path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


@pytest.mark.asyncio
async def test_create_nested_slug_and_duplicate(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    manager = Manager(str(repo))
    wt = await manager.create("team/alice", "HEAD", manual=True)
    assert Path(wt.path).name == "team+alice"
    assert wt.branch == "worktree-team+alice"
    assert Path(wt.path).is_dir()
    assert (
        subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=wt.path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        == wt.branch
    )
    with pytest.raises(ValueError, match="已存在"):
        await manager.create("team/alice", "HEAD", manual=True)


@pytest.mark.asyncio
async def test_create_setup_and_fast_recovery(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    local = repo / ".Licode" / "settings.local.yaml"
    local.parent.mkdir()
    local.write_text("permissions: {}\n", encoding="utf-8")
    (repo / ".worktreeinclude").write_text("*.env\n", encoding="utf-8")
    (repo / ".env").write_text("TOKEN=test\n", encoding="utf-8")
    (repo / ".husky").mkdir()
    node_modules = repo / "node_modules"
    node_modules.mkdir()

    manager = Manager(str(repo))
    wt = await manager.create("alice", "HEAD", manual=True)
    wt_path = Path(wt.path)
    assert (wt_path / ".Licode" / "settings.local.yaml").read_text(encoding="utf-8")
    assert (wt_path / ".env").read_text(encoding="utf-8") == "TOKEN=test\n"
    if os.name != "nt" or (wt_path / "node_modules").is_symlink():
        assert (wt_path / "node_modules").is_symlink()
    hooks = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=wt.path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert Path(hooks).resolve() == (repo / ".husky").resolve()

    manager.active.clear()

    async def fail_git(*_args, **_kwargs):
        raise AssertionError("快速恢复不应调用 Git")

    monkeypatch.setattr("Licode.worktree.create._run_git", fail_git)
    restored = await manager.create("alice", "HEAD", manual=True)
    assert restored.head_commit == wt.head_commit
