"""Git Worktree 隔离与生命周期管理。"""

from .lifecycle import (
    AutoCleanupReport,
    ExitAction,
    ExitOptions,
    ExitReport,
    WorktreeHasChangesError,
)
from .manager import DEFAULT_SYMLINK_DIRS, Manager, Worktree
from .session import WorktreeSession, clear_session, load_session, save_session
from .slug import flat_slug, validate_slug
from .sweep import EPHEMERAL_PATTERN, random_agent_name

__all__ = [
    "DEFAULT_SYMLINK_DIRS",
    "EPHEMERAL_PATTERN",
    "AutoCleanupReport",
    "ExitAction",
    "ExitOptions",
    "ExitReport",
    "Manager",
    "Worktree",
    "WorktreeHasChangesError",
    "WorktreeSession",
    "clear_session",
    "flat_slug",
    "load_session",
    "random_agent_name",
    "save_session",
    "validate_slug",
]
