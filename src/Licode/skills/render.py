"""渲染 Skill 正文与参数。"""

from .parser import substitute_arguments
from .types import Skill


def render_body(skill: Skill, args: str) -> str:
    had_placeholder = "$ARGUMENTS" in skill.prompt_body
    body = substitute_arguments(skill.prompt_body, args)
    if args and not had_placeholder:
        body = f"{body}\n\n## User Request\n\n{args}"
    if skill.allowed_tools:
        tools = ", ".join(skill.allowed_tools)
        prefix = (
            f"This skill is designed to use only these tools: {tools}. "
            "Prefer them over other tools when possible.\n\n---\n\n"
        )
        body = prefix + body
    return body
