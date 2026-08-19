import json
import os
import subprocess
from pathlib import Path

import pytest

from Licode.worktree import Manager, WorktreeSession, load_session, save_session


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


def sample_session(repo: Path, worktree: Path) -> WorktreeSession:
    return WorktreeSession(
        original_cwd=str(repo),
        worktree_path=str(worktree),
        worktree_name="alice",
        original_branch="main",
        original_head_commit="abc",
        session_id="session-id",
    )


def test_manager_validates_root_and_creates_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    manager = Manager(str(repo))
    assert Path(manager.worktree_dir).is_dir()
    assert manager.current_session() is None
    with pytest.raises(ValueError):
        Manager(str(tmp_path))


def test_session_round_trip_and_null(tmp_path: Path) -> None:
    path = tmp_path / "worktree_session.json"
    wt = tmp_path / "wt"
    wt.mkdir()
    session = sample_session(tmp_path, wt)
    save_session(path, session)
    assert load_session(path) == session
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {
        "original_cwd",
        "worktree_path",
        "worktree_name",
        "original_branch",
        "original_head_commit",
        "session_id",
        "hook_based",
    }
    save_session(path, None)
    assert path.read_text(encoding="utf-8") == "null"
    assert load_session(path) is None


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        '{"original_cwd": 1}',
        json.dumps(
            {
                "original_cwd": "root",
                "worktree_path": "wt",
                "worktree_name": "alice",
                "original_branch": "main",
                "original_head_commit": "abc",
                "session_id": "id",
                "hook_based": "false",
            }
        ),
        json.dumps(
            {
                "original_cwd": "root",
                "worktree_path": "wt",
                "worktree_name": "alice",
                "original_branch": "main",
                "original_head_commit": "abc",
                "session_id": "id",
                "extra": True,
            }
        ),
    ],
)
def test_session_rejects_invalid_shape_and_types(raw: str) -> None:
    with pytest.raises(ValueError):
        WorktreeSession.from_json(raw)


def test_atomic_save_failure_preserves_existing_file(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "worktree_session.json"
    path.write_text("old", encoding="utf-8")
    monkeypatch.setattr(os, "replace", lambda *_: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        save_session(path, None)
    assert path.read_text(encoding="utf-8") == "old"


def test_manager_loads_and_clears_stale_session(tmp_path: Path, capsys) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    session_path = repo / ".Licode" / "worktree_session.json"
    session_path.parent.mkdir(parents=True)
    missing = repo / ".Licode" / "worktrees" / "missing"
    save_session(session_path, sample_session(repo, missing))

    manager = Manager(str(repo))
    assert manager.current_session() is None
    assert session_path.read_text(encoding="utf-8") == "null"
    assert "session 对应的 Worktree 已丢失" in capsys.readouterr().err


def test_invalid_session_cleanup_failure_does_not_block_startup(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    repo = tmp_path / "repo"
    init_repo(repo)
    session_path = repo / ".Licode" / "worktree_session.json"
    session_path.parent.mkdir(parents=True)
    session_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "Licode.worktree.manager.clear_session",
        lambda _path: (_ for _ in ()).throw(OSError("只读")),
    )

    manager = Manager(str(repo))

    assert manager.current_session() is None
    assert "session 清理失败" in capsys.readouterr().err
