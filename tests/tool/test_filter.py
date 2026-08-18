from Licode.tool.filter import (
    ALL_AGENT_DISALLOWED_TOOLS,
    ASYNC_AGENT_ALLOWED_TOOLS,
    CUSTOM_AGENT_DISALLOWED_TOOLS,
    FilterParams,
    apply_agent_tool_filter,
    is_mcp_or_skill,
)


def test_constants() -> None:
    assert ALL_AGENT_DISALLOWED_TOOLS == ["Agent"]
    assert CUSTOM_AGENT_DISALLOWED_TOOLS == []
    assert "bash" in ASYNC_AGENT_ALLOWED_TOOLS


def test_filter_layers() -> None:
    all_names = ["Agent", "read_file", "bash", "TaskList", "mcp__search"]
    assert apply_agent_tool_filter(FilterParams(all_names, 0, False)) == [
        "read_file",
        "bash",
        "TaskList",
        "mcp__search",
    ]
    assert apply_agent_tool_filter(FilterParams(all_names, 0, True)) == [
        "read_file",
        "bash",
        "mcp__search",
    ]
    assert apply_agent_tool_filter(
        FilterParams(all_names, 2, False, allowed=["read_file", "bash"], disallowed=["bash"])
    ) == ["read_file"]


def test_mcp_recognition() -> None:
    assert is_mcp_or_skill("mcp__server__tool")
    assert not is_mcp_or_skill("TaskList")
