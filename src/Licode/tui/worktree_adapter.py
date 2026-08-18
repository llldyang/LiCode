"""Worktree Manager 到命令 UI 协议的适配层。"""

from collections.abc import Callable

from Licode.command import WorktreeSummary
from Licode.worktree import ExitAction, ExitOptions, Manager


class WorktreeAdapter:
    def __init__(self, manager: Manager, set_active_cwd: Callable[[str], None]) -> None:
        self.manager = manager
        self.set_active_cwd = set_active_cwd

    async def create(self, name: str) -> tuple[str, str]:
        worktree = await self.manager.create(name, "HEAD", manual=True)
        return worktree.path, worktree.branch

    def list(self) -> list[WorktreeSummary]:
        session = self.manager.current_session()
        active_name = session.worktree_name if session is not None else ""
        return [
            WorktreeSummary(
                name=item.name,
                path=item.path,
                branch=item.branch,
                active=item.name == active_name,
                manual=item.manual,
            )
            for item in self.manager.list()
        ]

    async def enter(self, name: str) -> None:
        session = await self.manager.enter(name)
        self.set_active_cwd(session.worktree_path)

    async def exit(self, action: str, discard: bool) -> bool:
        session = self.manager.current_session()
        if session is None:
            raise ValueError("当前没有 Worktree 会话")
        report = await self.manager.exit(
            session.worktree_name,
            ExitAction(action),
            ExitOptions(discard_changes=discard),
        )
        self.set_active_cwd(session.original_cwd)
        return report.removed

    async def remove(self, name: str, discard: bool) -> None:
        await self.manager.remove(name, ExitOptions(discard_changes=discard))


__all__ = ["WorktreeAdapter"]
