"""模块化系统提示、动态环境与启动横幅。"""

from .environment import Environment, gather_environment
from .modules import Module, fixed_modules, optional_modules
from .reminder import EXECUTE_DIRECTIVE, plan_reminder, system_reminder

CAT_BANNER = r""" /\_/\\
( o.o )
 > ^ <"""
READY_HINT = "Ready for your request."


def assemble_system(modules: list[Module]) -> str:
    """按优先级稳定装配非空模块。"""

    ordered = sorted(modules, key=lambda module: module.priority)
    return "\n\n".join(module.content for module in ordered if module.content)


def build_system_prompt() -> str:
    """构造跨轮逐字节稳定的系统提示。"""

    return assemble_system(fixed_modules() + optional_modules())


def render_banner(version: str, cwd: str) -> str:
    """生成包含应用信息和当前目录的启动横幅。"""

    return f"{CAT_BANNER}\nLiCode v{version}\n{cwd}\n{READY_HINT}"


__all__ = [
    "CAT_BANNER",
    "EXECUTE_DIRECTIVE",
    "READY_HINT",
    "Environment",
    "Module",
    "assemble_system",
    "build_system_prompt",
    "fixed_modules",
    "gather_environment",
    "optional_modules",
    "plan_reminder",
    "render_banner",
    "system_reminder",
]
