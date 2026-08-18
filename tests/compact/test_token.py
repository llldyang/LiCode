import math

from Licode.compact.token import estimate_tokens, message_chars, usage_anchor
from Licode.llm import Message, ToolCall, ToolResult, Usage


def test_estimate_tokens_uses_anchor_and_increment() -> None:
    first = Message(role="user", content="已计入")
    second = Message(role="assistant", content="x" * 350)
    assert estimate_tokens(0, [], 0) == 0
    assert estimate_tokens(1000, [first, second], 1) == 1000 + math.ceil(350 / 3.5)


def test_message_chars_includes_utf8_tools_and_results() -> None:
    message = Message(
        role="assistant",
        content="中",
        tool_calls=[ToolCall("id", "tool", '{"值":"中"}')],
        tool_results=[ToolResult("id", "结果")],
    )
    assert message_chars([message]) == sum(
        len(value.encode("utf-8")) for value in ("中", '{"值":"中"}', "结果")
    )


def test_usage_anchor_sums_all_fields() -> None:
    assert usage_anchor(Usage(100, 20, cache_write=30, cache_read=40)) == 190
