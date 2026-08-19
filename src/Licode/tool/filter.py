"""SubAgent 工具列表的多层过滤规则。"""

from dataclasses import dataclass, field

TEAMMATE_EXTRA_TOOLS: list[str] = [
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "SendMessage",
]
TEAM_LIFECYCLE_TOOLS: list[str] = ["TeamCreate", "TeamDelete"]
# TaskGet/TaskList/SendMessage 与第 13 章工具同名，Lead 仍需保留原有能力；
# 只有本章新引入且纯 Team 语义的两个任务工具需要从普通 Lead 隐藏。
MAIN_AGENT_TEAM_HIDDEN_TOOLS: list[str] = ["TaskCreate", "TaskUpdate"]
ALL_AGENT_DISALLOWED_TOOLS: list[str] = [
    "Agent",
    *TEAMMATE_EXTRA_TOOLS,
    *TEAM_LIFECYCLE_TOOLS,
]
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
    teammate: bool = False


def is_mcp_or_skill(name: str) -> bool:
    """本章仅按 MCP 命名前缀识别可后台运行的扩展工具。"""

    return name.startswith("mcp__")


def apply_main_agent_tool_filter(all_names: list[str]) -> list[str]:
    """保持普通 Lead 的既有工具集，不暴露仅供 Team 队员使用的新工具。"""

    hidden = set(MAIN_AGENT_TEAM_HIDDEN_TOOLS)
    return [name for name in all_names if name not in hidden]


def apply_agent_tool_filter(params: FilterParams) -> list[str]:
    """按全局、来源、后台、黑名单、白名单顺序收窄工具集。"""

    globally_denied = set(ALL_AGENT_DISALLOWED_TOOLS)
    if params.teammate:
        globally_denied.difference_update(TEAMMATE_EXTRA_TOOLS)
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
    if params.teammate:
        # 协作工具属于 Team 运行时能力，不要求每个角色文件重复声明。
        selected = set(result)
        denied = set(params.disallowed)
        selected.update(
            name for name in TEAMMATE_EXTRA_TOOLS if name in params.all and name not in denied
        )
        result = [name for name in params.all if name in selected and name != "Agent"]
    return result
