"""Team 与后台 SubAgent 共用的 TaskGet 工具。"""

import json
from typing import Any

from Licode.team.tasks import Store
from Licode.tool import Result

from .team_create import _object, _required_text


class TaskGetTool:
    read_only = True
    is_system = False

    def __init__(self, manager, fallback=None) -> None:
        self.manager = manager
        self.fallback = fallback

    def name(self) -> str:
        return "TaskGet"

    def description(self) -> str:
        return "查询共享 Team 任务或后台 SubAgent 任务详情。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        try:
            value = _object(args)
            task_id = _required_text(value, "task_id")
            for team in reversed(self.manager.list_()):
                try:
                    task = await Store(team.tasks_path).get(task_id)
                except KeyError:
                    continue
                return Result(json.dumps(task.to_dict(include_ready=True), ensure_ascii=False))
            if self.fallback is not None:
                return await self.fallback.execute(args)
            raise KeyError(f"任务不存在: {task_id}")
        except Exception as exc:
            return Result(str(exc), is_error=True)
