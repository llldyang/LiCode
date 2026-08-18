from pathlib import Path

import pytest

from Licode.compact import CompactCircuitBreaker, TriggerKind
from Licode.compact.layer2 import (
    _join_after_summary,
    force_compact,
    group_by_user_turn,
    pick_recent_tail,
    ptl_retry,
    run_summary,
)
from Licode.compact.token import estimate_tokens
from Licode.conversation import Conversation
from Licode.llm import Message, PromptTooLongError, StreamEvent, ToolCall, ToolResult

from .conftest import FakeCompactProvider, make_input, summary_text


def test_pick_recent_tail_satisfies_both_lower_bounds() -> None:
    messages = [
        Message(role="user" if index % 2 == 0 else "assistant", content="x" * 7000)
        for index in range(6)
    ]
    recent = pick_recent_tail(messages)
    assert len(recent) >= 5
    assert estimate_tokens(0, recent, 0) >= 10000


def test_pick_recent_tail_moves_before_tool_result_pair() -> None:
    messages = [
        Message(
            role="assistant",
            tool_calls=[ToolCall("call-a", "read_file", "{}")],
        ),
        Message(
            role="tool",
            tool_results=[ToolResult("call-a", "x" * 35000)],
        ),
        Message(role="assistant", content="1"),
        Message(role="user", content="2"),
        Message(role="assistant", content="3"),
        Message(role="user", content="4"),
    ]
    recent = pick_recent_tail(messages)
    assert recent[0].role == "assistant"
    assert recent[0].tool_calls[0].id == "call-a"
    assert recent[1].tool_results[0].tool_call_id == "call-a"


def test_join_after_summary_avoids_consecutive_user() -> None:
    summary = Message(role="user", content="摘要")
    joined = _join_after_summary(summary, [Message(role="user", content="近期")])
    assert [message.role for message in joined] == ["user", "assistant", "user"]


def test_group_by_user_turn() -> None:
    messages = [
        Message(role="user", content="u1"),
        Message(role="assistant", content="a1"),
        Message(role="tool"),
        Message(role="user", content="u2"),
        Message(role="assistant", content="a2"),
    ]
    assert [len(group) for group in group_by_user_turn(messages)] == [3, 2]


@pytest.mark.asyncio
async def test_run_summary_has_no_tools_and_builds_recovery(tmp_path: Path) -> None:
    conversation = Conversation()
    conversation.add_user("用户原话")
    provider = FakeCompactProvider(
        [[StreamEvent(text=summary_text("包含用户原话")), StreamEvent(done=True)]]
    )
    input_ = make_input(tmp_path, provider, conversation, trigger=TriggerKind.MANUAL)

    messages = await run_summary(input_)

    assert provider.requests[0].tools is None
    assert "## 历史会话摘要" in messages[0].content
    assert "## 最近读过的文件" in messages[0].content
    assert "## 当前可用工具" in messages[0].content
    assert "## 边界提示" in messages[0].content
    assert "草稿" not in messages[0].content


def _turns(count: int) -> Conversation:
    conversation = Conversation()
    for index in range(count):
        conversation.add_user(f"u{index}")
        conversation.add_assistant(f"a{index}")
    return conversation


@pytest.mark.asyncio
async def test_ptl_retry_drops_one_group_for_first_three_retries(tmp_path: Path) -> None:
    error = PromptTooLongError("too long")
    provider = FakeCompactProvider(
        [
            [StreamEvent(err=error)],
            [StreamEvent(err=error)],
            [StreamEvent(err=error)],
            [StreamEvent(text=summary_text()), StreamEvent(done=True)],
        ]
    )
    input_ = make_input(tmp_path, provider, _turns(5))
    result = await ptl_retry(input_, _turns(5).messages(), error)
    assert "## 1 主要请求和意图" in result
    counts = [request.messages[0].content.count("user: u") for request in provider.requests]
    assert counts == [4, 3, 2, 1]


@pytest.mark.asyncio
async def test_run_summary_ptl_group_sequence(tmp_path: Path) -> None:
    error = PromptTooLongError("too long")
    provider = FakeCompactProvider(
        [
            [StreamEvent(err=error)],
            [StreamEvent(err=error)],
            [StreamEvent(err=error)],
            [StreamEvent(text=summary_text()), StreamEvent(done=True)],
        ]
    )
    input_ = make_input(tmp_path, provider, _turns(5))
    await run_summary(input_)
    counts = [request.messages[0].content.count("user: u") for request in provider.requests]
    assert counts == [5, 4, 3, 2]


@pytest.mark.asyncio
async def test_ptl_retry_switches_to_percentage_drop(tmp_path: Path) -> None:
    error = PromptTooLongError("too long")
    provider = FakeCompactProvider(
        [
            [StreamEvent(err=error)],
            [StreamEvent(err=error)],
            [StreamEvent(err=error)],
            [StreamEvent(err=error)],
            [StreamEvent(text=summary_text()), StreamEvent(done=True)],
        ]
    )
    input_ = make_input(tmp_path, provider, _turns(10))
    await run_summary(input_)
    counts = [request.messages[0].content.count("user: u") for request in provider.requests]
    assert counts == [10, 9, 8, 7, 5]


@pytest.mark.asyncio
async def test_ptl_retry_never_sends_empty_messages(tmp_path: Path) -> None:
    error = PromptTooLongError("too long")
    provider = FakeCompactProvider([[StreamEvent(err=error)], [StreamEvent(err=error)]])
    input_ = make_input(tmp_path, provider, _turns(2))
    with pytest.raises(PromptTooLongError):
        await run_summary(input_)
    assert len(provider.requests) == 2
    assert all("user: u" in request.messages[0].content for request in provider.requests)


@pytest.mark.asyncio
async def test_force_compact_does_not_touch_circuit_breaker(tmp_path: Path) -> None:
    tracking = CompactCircuitBreaker()
    tracking.record_failure()
    provider = FakeCompactProvider([[StreamEvent(err=RuntimeError("失败"))]])
    input_ = make_input(
        tmp_path,
        provider,
        _turns(1),
        trigger=TriggerKind.MANUAL,
        tracking=tracking,
    )
    with pytest.raises(RuntimeError):
        await force_compact(input_)
    tracking.record_failure()
    assert not tracking.tripped()
