"""Team 与后台 SubAgent 共用的 TaskList 工具。"""

import json
from typing import Any

from Licode.agent.team_hook import teammate_context_from_ctx
from Licode.team.tasks import Filter, Status, Store
from Licode.tool import Result

from .team_create import _object


class TaskListTool:
    read_only = True
    is_system = False

    def __init__(self, manager, fallback=None) -> None:
        self.manager = manager
        self.fallback = fallback

    def name(self) -> str:
        return "TaskList"

    def description(self) -> str:
        return "列出当前 Team 的共享任务，或列出后台 SubAgent 任务。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": [item.value for item in Status],
                }
            },
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        try:
            value = _object(args)
            use_team = (
                teammate_context_from_ctx() is not None
                or self.manager.coordinator_mode
                or "status" in value
            )
            if not use_team and self.fallback is not None:
                return await self.fallback.execute(args)
            status_raw = value.get("status")
            if status_raw is not None and not isinstance(status_raw, str):
                raise ValueError("status 必须是字符串")
            status = Status(status_raw) if status_raw else None
            team = self.manager.current_team()
            tasks = await Store(team.tasks_path).list_(Filter(status=status))
            return Result(
                json.dumps(
                    [task.to_dict(include_ready=True) for task in tasks],
                    ensure_ascii=False,
                )
            )
        except Exception as exc:
            return Result(str(exc), is_error=True)
