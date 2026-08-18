"""SubAgent 工具列表的多层过滤规则。"""

from dataclasses import dataclass, field

ALL_AGENT_DISALLOWED_TOOLS: list[str] = ["Agent"]
CUSTOM_AGENT_DISALLOWED_TOOLS: list[str] = []
ASYNC_AGENT_ALLOWED_TOOLS: list[str] = [
    "read_file",
    "write_file",
    "edit_file",
    "glob",
    "grep",
    "bash",
    "load_skill",
    "install_skill",
    "LoadSkill",
    "InstallSkill",
]


@dataclass
class FilterParams:
    all: list[str]
    source: int
    background: bool
    allowed: list[str] = field(default_factory=list)
    disallowed: list[str] = field(default_factory=list)


def is_mcp_or_skill(name: str) -> bool:
    """本章仅按 MCP 命名前缀识别可后台运行的扩展工具。"""

    return name.startswith("mcp__")


def apply_agent_tool_filter(params: FilterParams) -> list[str]:
    """按全局、来源、后台、黑名单、白名单顺序收窄工具集。"""

    globally_denied = set(ALL_AGENT_DISALLOWED_TOOLS)
    result = [name for name in params.all if name not in globally_denied]
    if params.source >= 1:
        custom_denied = set(CUSTOM_AGENT_DISALLOWED_TOOLS)
        result = [name for name in result if name not in custom_denied]
    if params.background:
        async_allowed = set(ASYNC_AGENT_ALLOWED_TOOLS)
        result = [name for name in result if name in async_allowed or is_mcp_or_skill(name)]
    denied = set(params.disallowed)
    result = [name for name in result if name not in denied]
    if params.allowed:
        allowed = set(params.allowed)
        result = [name for name in result if name in allowed]
    return result
