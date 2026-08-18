"""Worktree 进入、退出、删除和自动清理。"""

from __future__ import annotations

import asyncio
import os
import secrets
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from .git import _has_worktree_changes, _run_git
from .session import WorktreeSession, save_session

if TYPE_CHECKING:
    from .manager import Manager, Worktree


class ExitAction(StrEnum):
    KEEP = "keep"
    REMOVE = "remove"


@dataclass
class ExitOptions:
    discard_changes: bool = False


@dataclass
class ExitReport:
    removed: bool
    path: str
    branch: str


@dataclass
class AutoCleanupReport:
    kept: bool
    path: str = ""
    branch: str = ""


class WorktreeHasChangesError(RuntimeError):
    """Worktree 有未提交修改或创建后新增的 commit。"""


async def enter_worktree(manager: Manager, name: str) -> WorktreeSession:
    async with manager.lock:
        worktree = manager.active.get(name)
    if worktree is None:
        raise ValueError(f"Worktree 不存在: {name}")
    try:
        original_branch = await _run_git(manager.repo_root, "rev-parse", "--abbrev-ref", "HEAD")
        original_head = await _run_git(manager.repo_root, "rev-parse", "HEAD")
    except (OSError, RuntimeError):
        original_branch = ""
        original_head = ""
    session = WorktreeSession(
        original_cwd=str(Path.cwd()),
        worktree_path=worktree.path,
        worktree_name=name,
        original_branch=original_branch,
        original_head_commit=original_head,
        session_id=secrets.token_hex(8),
    )
    async with manager.lock:
        manager._current_session = session
        save_session(Path(manager.session_file), session)
    return session


def _coerce_action(action: object) -> ExitAction:
    if isinstance(action, ExitAction):
        return action
    return ExitAction(str(action))


def _coerce_options(opts: object) -> ExitOptions:
    if isinstance(opts, ExitOptions):
        return opts
    raise TypeError("opts 必须是 ExitOptions")


async def _remove_registered(manager: Manager, worktree: Worktree) -> None:
    await _run_git(
        manager.repo_root,
        "worktree",
        "remove",
        "--force",
        worktree.path,
    )
    await asyncio.sleep(0.1)
    await _run_git(manager.repo_root, "branch", "-D", worktree.branch)
    async with manager.lock:
        manager.active.pop(worktree.name, None)


async def exit_worktree(
    manager: Manager,
    name: str,
    action: object,
    opts: object,
) -> ExitReport:
    selected_action = _coerce_action(action)
    options = _coerce_options(opts)
    async with manager.lock:
        session = manager._current_session
        worktree = manager.active.get(name)
    if session is None or session.worktree_name != name:
        raise ValueError("只能退出当前 Worktree 会话")
    if worktree is None:
        raise ValueError(f"Worktree 不存在: {name}")
    if (
        selected_action is ExitAction.REMOVE
        and not options.discard_changes
        and await _has_worktree_changes(worktree.path, worktree.head_commit)
    ):
        raise WorktreeHasChangesError("Worktree 有未提交修改或新增 commit，拒绝删除")

    with suppress(OSError):
        os.chdir(session.original_cwd)
    async with manager.lock:
        if manager._current_session is not session:
            raise RuntimeError("Worktree 会话已变化")
        manager._current_session = None
        save_session(Path(manager.session_file), None)
    if selected_action is ExitAction.REMOVE:
        await _remove_registered(manager, worktree)
    return ExitReport(
        removed=selected_action is ExitAction.REMOVE,
        path=worktree.path,
        branch=worktree.branch,
    )


async def remove_worktree(manager: Manager, name: str, opts: object) -> None:
    options = _coerce_options(opts)
    async with manager.lock:
        worktree = manager.active.get(name)
        session = manager._current_session
    if worktree is None:
        raise ValueError(f"Worktree 不存在: {name}")
    if session is not None and session.worktree_name == name:
        raise ValueError("当前 Worktree 请使用 exit 退出")
    if not options.discard_changes and await _has_worktree_changes(
        worktree.path, worktree.head_commit
    ):
        raise WorktreeHasChangesError("Worktree 有未提交修改或新增 commit，拒绝删除")
    await _remove_registered(manager, worktree)


async def auto_cleanup_worktree(manager: Manager, name: str) -> AutoCleanupReport:
    async with manager.lock:
        worktree = manager.active.get(name)
    if worktree is None:
        raise ValueError(f"Worktree 不存在: {name}")
    if worktree.manual:
        return AutoCleanupReport(True, worktree.path, worktree.branch)
    if await _has_worktree_changes(worktree.path, worktree.head_commit):
        return AutoCleanupReport(True, worktree.path, worktree.branch)
    await remove_worktree(manager, name, ExitOptions(discard_changes=True))
    return AutoCleanupReport(False)
