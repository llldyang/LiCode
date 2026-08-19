"""TaskUpdate 协作工具。"""

import json
from typing import Any

from Licode.team.tasks import Patch, Status, Store
from Licode.tool import Result

from .team_create import _object, _required_text

_LIST_FIELDS = ("add_blocks", "add_blocked_by", "remove_blocks", "remove_blocked_by")


class TaskUpdateTool:
    read_only = False
    is_system = False

    def __init__(self, manager) -> None:
        self.manager = manager

    def name(self) -> str:
        return "TaskUpdate"

    def description(self) -> str:
        return "更新 Team 共享任务及其双向依赖关系。"

    def parameters(self) -> dict[str, Any]:
        properties: dict[str, Any] = {
            "task_id": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "status": {"type": "string", "enum": [item.value for item in Status]},
            "assignee": {"type": "string"},
        }
        properties.update(
            {name: {"type": "array", "items": {"type": "string"}} for name in _LIST_FIELDS}
        )
        return {
            "type": "object",
            "properties": properties,
            "required": ["task_id"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        try:
            value = _object(args)
            lists: dict[str, list[str]] = {}
            for field_name in _LIST_FIELDS:
                item = value.get(field_name, [])
                if not isinstance(item, list) or any(not isinstance(entry, str) for entry in item):
                    raise ValueError(f"{field_name} 必须是字符串数组")
                lists[field_name] = item
            status_raw = value.get("status")
            if status_raw is not None and not isinstance(status_raw, str):
                raise ValueError("status 必须是字符串")
            for text_field in ("title", "description", "assignee"):
                if text_field in value and not isinstance(value[text_field], str):
                    raise ValueError(f"{text_field} 必须是字符串")
            title = value.get("title")
            description = value.get("description")
            assignee = value.get("assignee")
            assert title is None or isinstance(title, str)
            assert description is None or isinstance(description, str)
            assert assignee is None or isinstance(assignee, str)
            patch = Patch(
                title=title,
                description=description,
                status=Status(status_raw) if status_raw else None,
                assignee=assignee,
                **lists,
            )
            team = self.manager.current_team()
            task_id = _required_text(value, "task_id")
            await Store(team.tasks_path).update(task_id, patch)
            task = await Store(team.tasks_path).get(task_id)
            return Result(json.dumps(task.to_dict(include_ready=True), ensure_ascii=False))
        except Exception as exc:
            return Result(str(exc), is_error=True)
