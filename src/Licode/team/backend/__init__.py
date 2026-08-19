"""Team 队员执行后端抽象。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from Licode.team.types import BackendType


@dataclass
class SpawnRequest:
    team_name: str
    member_name: str
    agent_id: str
    worktree_path: str
    session_dir: str
    agent_type: str
    model: str
    initial_prompt: str
    plan_mode_required: bool
    sub_agent: Any = None
    conv: Any = None
    task_mgr: Any = None


class Backend(Protocol):
    def type(self) -> BackendType: ...

    async def spawn(self, req: SpawnRequest) -> tuple[str, str]: ...

    async def wake(self, pane_id: str, agent_id: str) -> None: ...

    async def kill(self, pane_id: str, agent_id: str) -> None: ...


def new_backend(backend_type: BackendType, *, task_mgr: Any = None) -> Backend:
    if backend_type is BackendType.TMUX:
        from .tmux import TmuxBackend

        return TmuxBackend()
    if backend_type is BackendType.ITERM2:
        from .iterm2 import Iterm2Backend

        return Iterm2Backend()
    if task_mgr is None:
        raise ValueError("in-process 后端需要 task_mgr")
    from .inprocess import InProcessBackend

    return InProcessBackend(task_mgr)


__all__ = ["Backend", "BackendType", "SpawnRequest", "new_backend"]
