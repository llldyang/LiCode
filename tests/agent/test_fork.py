from Licode.agent.fork import build_forked_messages, is_fork_context
from Licode.llm import Message, ToolCall, ToolResult


def test_empty_parent() -> None:
    messages = build_forked_messages([], "检查项目")
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert "<fork_boilerplate>" in messages[0].content
    assert "检查项目" in messages[0].content


def test_complete_pair_is_preserved() -> None:
    parent = [
        Message(role="assistant", tool_calls=[ToolCall("1", "read_file", "{}")]),
        Message(role="tool", tool_results=[ToolResult("1", "ok")]),
    ]
    messages = build_forked_messages(parent, "next")
    assert len(messages) == 3
    assert messages[1].tool_results[0].content == "ok"


def test_dangling_calls_get_placeholders() -> None:
    parent = [
        Message(
            role="assistant",
            tool_calls=[ToolCall("1", "a", "{}"), ToolCall("2", "b", "{}")],
        )
    ]
    messages = build_forked_messages(parent, "next")
    assert [item.tool_call_id for item in messages[-2].tool_results] == ["1", "2"]
    assert all(item.is_error for item in messages[-2].tool_results)
    assert is_fork_context(messages)
    assert not is_fork_context(parent)


def test_dangling_call_is_repaired_before_later_history() -> None:
    parent = [
        Message(role="assistant", tool_calls=[ToolCall("1", "a", "{}")]),
        Message(role="user", content="later"),
    ]

    messages = build_forked_messages(parent, "next")

    assert [message.role for message in messages] == ["assistant", "tool", "user", "user"]
    assert messages[1].tool_results[0].tool_call_id == "1"
