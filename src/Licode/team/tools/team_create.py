"""TeamCreate 工具。"""

import json
from typing import Any

from Licode.tool import Result


class TeamCreateTool:
    read_only = False
    is_system = False

    def __init__(self, manager) -> None:
        self.manager = manager

    def name(self) -> str:
        return "TeamCreate"

    def description(self) -> str:
        return "创建一个持久化 Agent Team，并自动选择执行后端。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "team_name": {"type": "string"},
                "description": {"type": "string"},
                "agent_type": {"type": "string"},
            },
            "required": ["team_name"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        try:
            value = _object(args)
            name = _required_text(value, "team_name")
            description = _optional_text(value, "description")
            _optional_text(value, "agent_type")
            team = await self.manager.create(name, description)
            return Result(
                json.dumps(
                    {
                        "team_name": team.sanitized_name,
                        "backend": team.backend.value,
                        "config_path": team.config_path,
                    },
                    ensure_ascii=False,
                )
            )
        except Exception as exc:
            return Result(str(exc), is_error=True)


def _object(args: str) -> dict[str, object]:
    value = json.loads(args or "{}")
    if not isinstance(value, dict):
        raise ValueError("参数必须是 JSON 对象")
    return value


def _required_text(value: dict[str, object], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"{name} 必须是非空字符串")
    return item.strip()


def _optional_text(value: dict[str, object], name: str) -> str:
    item = value.get(name, "")
    if not isinstance(item, str):
        raise ValueError(f"{name} 必须是字符串")
    return item.strip()
