import asyncio
import subprocess
from pathlib import Path

import pytest

from Licode.worktree.git import (
    _has_worktree_changes,
    _resolve_head_sha_from_fs,
    _run_git,
)


def init_repo(path: Path) -> None:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True)


@pytest.mark.asyncio
async def test_run_git_is_non_interactive(tmp_path: Path, monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Process:
        returncode = 0

        async def communicate(self):
            return b"ok\n", b""

    async def fake_create(*args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create)
    assert await _run_git(tmp_path, "status") == "ok"
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ASKPASS"] == ""
    assert captured["stdin"] is asyncio.subprocess.DEVNULL
    assert captured["cwd"] == str(tmp_path)


@pytest.mark.asyncio
async def test_change_detection_and_filesystem_head_resolution(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    wt = tmp_path / "wt"
    init_repo(repo)
    base = await _run_git(repo, "rev-parse", "HEAD")
    await _run_git(repo, "worktree", "add", "-b", "worktree-test", str(wt), "HEAD")

    assert _resolve_head_sha_from_fs(wt) == base
    assert not await _has_worktree_changes(wt, base)
    (wt / "README.md").write_text("changed\n", encoding="utf-8")
    assert await _has_worktree_changes(wt, base)


@pytest.mark.asyncio
async def test_change_detection_fails_closed(tmp_path: Path) -> None:
    assert await _has_worktree_changes(tmp_path / "missing", "HEAD")
