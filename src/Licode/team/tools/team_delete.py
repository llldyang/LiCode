"""TeamDelete 工具。"""

from typing import Any

from Licode.tool import Result

from .team_create import _object, _required_text


class TeamDeleteTool:
    read_only = False
    is_system = False

    def __init__(self, manager) -> None:
        self.manager = manager

    def name(self) -> str:
        return "TeamDelete"

    def description(self) -> str:
        return "删除 Team；有活跃成员时需要 force=true。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "team_name": {"type": "string"},
                "force": {"type": "boolean", "default": False},
            },
            "required": ["team_name"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        try:
            value = _object(args)
            team_name = _required_text(value, "team_name")
            force = value.get("force", False)
            if not isinstance(force, bool):
                raise ValueError("force 必须是布尔值")
            await self.manager.delete(team_name, force)
            return Result(f"Team 已删除: {team_name}")
        except Exception as exc:
            return Result(str(exc), is_error=True)
