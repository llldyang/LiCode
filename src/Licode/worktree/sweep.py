"""过期临时 Worktree 的保守清理。"""

from __future__ import annotations

import re
import secrets
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .git import _has_worktree_changes, _run_git
from .lifecycle import ExitOptions

if TYPE_CHECKING:
    from .manager import Manager

EPHEMERAL_PATTERN = re.compile(r"^agent-a[0-9a-f]{7}$")


def random_agent_name() -> str:
    return "agent-a" + secrets.token_hex(4)[:7]


async def sweep_stale_worktrees(manager: Manager, cutoff: datetime) -> list[str]:
    removed: list[str] = []
    current = manager.current_session()
    current_path = str(Path(current.worktree_path).resolve()) if current is not None else ""
    root = Path(manager.worktree_dir)
    for directory in root.iterdir():
        if not directory.is_dir() or EPHEMERAL_PATTERN.fullmatch(directory.name) is None:
            continue
        if directory.stat().st_mtime > cutoff.timestamp():
            continue
        if str(directory.resolve()) == current_path:
            continue
        worktree = manager.get(directory.name)
        if worktree is None:
            continue
        if await _has_worktree_changes(directory, worktree.head_commit):
            continue
        try:
            unpushed = await _run_git(
                directory,
                "rev-list",
                "--max-count=1",
                "HEAD",
                "--not",
                "--remotes",
            )
        except (OSError, RuntimeError):
            continue
        if unpushed:
            continue
        try:
            await manager.remove(
                worktree.name,
                ExitOptions(discard_changes=True),
            )
        except (OSError, RuntimeError, ValueError):
            continue
        removed.append(worktree.name)
    return removed
