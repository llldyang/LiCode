from Licode.tool.filter import (
    ALL_AGENT_DISALLOWED_TOOLS,
    ASYNC_AGENT_ALLOWED_TOOLS,
    CUSTOM_AGENT_DISALLOWED_TOOLS,
    MAIN_AGENT_TEAM_HIDDEN_TOOLS,
    TEAM_LIFECYCLE_TOOLS,
    TEAMMATE_EXTRA_TOOLS,
    FilterParams,
    apply_agent_tool_filter,
    apply_main_agent_tool_filter,
    is_mcp_or_skill,
)


def test_constants() -> None:
    assert ALL_AGENT_DISALLOWED_TOOLS == [
        "Agent",
        *TEAMMATE_EXTRA_TOOLS,
        *TEAM_LIFECYCLE_TOOLS,
    ]
    assert CUSTOM_AGENT_DISALLOWED_TOOLS == []
    assert "bash" in ASYNC_AGENT_ALLOWED_TOOLS


def test_filter_layers() -> None:
    all_names = ["Agent", "read_file", "bash", "TaskList", "mcp__search"]
    assert apply_agent_tool_filter(FilterParams(all_names, 0, False)) == [
        "read_file",
        "bash",
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


def test_team_tools_only_visible_to_teammates() -> None:
    all_names = ["read_file", *TEAMMATE_EXTRA_TOOLS, *TEAM_LIFECYCLE_TOOLS]
    assert apply_agent_tool_filter(FilterParams(all_names, 0, False)) == ["read_file"]
    assert apply_agent_tool_filter(FilterParams(all_names, 0, False, teammate=True)) == [
        "read_file",
        *TEAMMATE_EXTRA_TOOLS,
    ]


def test_main_agent_hides_only_new_team_task_tools() -> None:
    all_names = [
        "read_file",
        "TaskList",
        "SendMessage",
        *MAIN_AGENT_TEAM_HIDDEN_TOOLS,
        *TEAM_LIFECYCLE_TOOLS,
    ]
    assert apply_main_agent_tool_filter(all_names) == [
        "read_file",
        "TaskList",
        "SendMessage",
        *TEAM_LIFECYCLE_TOOLS,
    ]
