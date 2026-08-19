"""按需加载完整 Skill SOP 的系统工具。"""

import json
from typing import Any

from Licode.skills.active import ActiveSkills, current_active_skills
from Licode.skills.catalog import Catalog
from Licode.skills.render import render_body

from . import Result


class LoadSkillTool:
    read_only = True
    is_system = True
    is_system_tool = True
    is_concurrency_safe = False

    def __init__(self, catalog: Catalog, active: ActiveSkills) -> None:
        self._catalog = catalog
        self._active = active

    def name(self) -> str:
        return "LoadSkill"

    def description(self) -> str:
        return "按名称加载并激活 Skill 的完整操作指令。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "要激活的 Skill 名称"}},
            "required": ["name"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            return Result(f"参数 JSON 非法: {exc}", is_error=True)
        name = data.get("name") if isinstance(data, dict) else None
        if not isinstance(name, str) or not name.strip():
            return Result("缺少字符串参数: name", is_error=True)
        skill = self._catalog.get(name.strip())
        if skill is None:
            available = ", ".join(self._catalog.names()) or "(none)"
            return Result(f"unknown skill: {name}; available: {available}", is_error=True)
        # 自然语言触发与显式 /skill 命令共享渲染逻辑，确保工具提示也进入 SOP。
        current_active_skills(self._active).activate(skill.name, render_body(skill, ""))
        return Result(f"Skill {skill.name} activated. SOP pinned to env context.")


LoadSkill = LoadSkillTool
