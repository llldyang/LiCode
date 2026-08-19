"""同一事件循环内运行队员的后端。"""

from __future__ import annotations

from typing import Any

from Licode.team.types import BackendType

from . import SpawnRequest


class InProcessBackend:
    def __init__(self, task_mgr: Any) -> None:
        self._task_mgr = task_mgr

    def type(self) -> BackendType:
        return BackendType.IN_PROCESS

    async def spawn(self, req: SpawnRequest) -> tuple[str, str]:
        if req.sub_agent is None or req.conv is None:
            raise ValueError("in-process spawn 缺少 sub_agent 或 conv")
        task_id = await self._task_mgr.launch(
            req.sub_agent,
            req.conv,
            req.member_name,
            req.initial_prompt,
        )
        return "", task_id

    async def wake(self, pane_id: str, agent_id: str) -> None:
        del pane_id, agent_id

    async def kill(self, pane_id: str, agent_id: str) -> None:
        del pane_id
        await self._task_mgr.stop(agent_id)
