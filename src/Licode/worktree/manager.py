"""Git Worktree 管理器与元数据。"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .git import _resolve_head_sha_from_fs
from .session import WorktreeSession, clear_session, load_session

DEFAULT_SYMLINK_DIRS = ["node_modules", ".venv", "vendor"]
_EPHEMERAL_PATTERN = re.compile(r"^agent-a[0-9a-f]{7}$")


@dataclass
class Worktree:
    name: str
    path: str
    branch: str
    based_on: str
    head_commit: str
    created: datetime
    manual: bool


class Manager:
    """管理单仓库内的 Worktree 生命周期与当前会话。"""

    def __init__(self, repo_root: str) -> None:
        root = Path(repo_root).resolve()
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_ASKPASS"] = ""
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError("不是 Git 仓库根目录")
        discovered = Path(result.stdout.strip()).resolve()
        if os.path.normcase(str(discovered)) != os.path.normcase(str(root)):
            raise ValueError("repo_root 必须是 Git 仓库根目录")

        self.repo_root = str(root)
        self.worktree_dir = str(root / ".Licode" / "worktrees")
        self.session_file = str(root / ".Licode" / "worktree_session.json")
        self.symlink_dirs = list(DEFAULT_SYMLINK_DIRS)
        self.lock = asyncio.Lock()
        self.active: dict[str, Worktree] = {}
        self._current_session: WorktreeSession | None = None
        self._pending_names: set[str] = set()
        Path(self.worktree_dir).mkdir(parents=True, exist_ok=True)
        self._load_current_session()
        self._restore_active()
        self._warn_missing_gitignore_entries()

    def _load_current_session(self) -> None:
        path = Path(self.session_file)
        try:
            session = load_session(path)
        except (OSError, TypeError, ValueError) as exc:
            print(f"worktree: session 文件无效，已清空: {exc}", file=sys.stderr)
            clear_session(path)
            return
        if session is not None and not Path(session.worktree_path).is_dir():
            print("worktree: session worktree gone, cleared", file=sys.stderr)
            clear_session(path)
            return
        self._current_session = session

    def _restore_active(self) -> None:
        for directory in Path(self.worktree_dir).iterdir():
            if not directory.is_dir():
                continue
            head_sha = _resolve_head_sha_from_fs(directory)
            if not head_sha:
                continue
            flat = directory.name
            name = flat.replace("+", "/")
            self.active[name] = Worktree(
                name=name,
                path=str(directory.resolve()),
                branch=f"worktree-{flat}",
                based_on=head_sha,
                head_commit=head_sha,
                created=datetime.fromtimestamp(directory.stat().st_mtime),
                manual=_EPHEMERAL_PATTERN.fullmatch(flat) is None,
            )

    def _warn_missing_gitignore_entries(self) -> None:
        path = Path(self.repo_root) / ".gitignore"
        try:
            lines = {line.strip() for line in path.read_text(encoding="utf-8").splitlines()}
        except OSError:
            lines = set()
        for expected in (".Licode/worktrees/", ".Licode/worktree_session.json"):
            if expected not in lines:
                print(f"worktree: 建议在 .gitignore 中加入 {expected}", file=sys.stderr)

    async def create(self, name: str, base_ref: str = "HEAD", manual: bool = False) -> Worktree:
        from .create import create_worktree

        return await create_worktree(self, name, base_ref, manual)

    async def enter(self, name: str) -> WorktreeSession:
        from .lifecycle import enter_worktree

        return await enter_worktree(self, name)

    async def exit(self, name: str, action: object, opts: object):
        from .lifecycle import exit_worktree

        return await exit_worktree(self, name, action, opts)

    async def remove(self, name: str, opts: object) -> None:
        from .lifecycle import remove_worktree

        await remove_worktree(self, name, opts)

    async def auto_cleanup(self, name: str):
        from .lifecycle import auto_cleanup_worktree

        return await auto_cleanup_worktree(self, name)

    async def sweep_stale(self, cutoff: datetime) -> list[str]:
        from .sweep import sweep_stale_worktrees

        return await sweep_stale_worktrees(self, cutoff)

    def list(self) -> list[Worktree]:
        return sorted(self.active.values(), key=lambda item: item.name)

    def get(self, name: str) -> Worktree | None:
        return self.active.get(name)

    def current_session(self) -> WorktreeSession | None:
        return self._current_session
