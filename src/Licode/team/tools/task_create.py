"""TaskCreate 协作工具。"""

import json
from typing import Any

from Licode.team.tasks import Store, Task
from Licode.tool import Result

from .team_create import _object, _optional_text, _required_text


class TaskCreateTool:
    read_only = False
    is_system = False

    def __init__(self, manager) -> None:
        self.manager = manager

    def name(self) -> str:
        return "TaskCreate"

    def description(self) -> str:
        return "在当前 Team 的共享任务列表中创建任务。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "assignee": {"type": "string"},
                "blocked_by": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["title"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        try:
            value = _object(args)
            blocked_by = value.get("blocked_by", [])
            if not isinstance(blocked_by, list) or any(
                not isinstance(item, str) for item in blocked_by
            ):
                raise ValueError("blocked_by 必须是字符串数组")
            team = self.manager.current_team()
            task_id = await Store(team.tasks_path).create(
                Task(
                    title=_required_text(value, "title"),
                    description=_optional_text(value, "description"),
                    assignee=_optional_text(value, "assignee"),
                    blocked_by=list(blocked_by),
                )
            )
            return Result(json.dumps({"task_id": task_id}))
        except Exception as exc:
            return Result(str(exc), is_error=True)
