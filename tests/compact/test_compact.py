from pathlib import Path

import pytest

from Licode.compact import CompactCircuitBreaker, ContentReplacementState, TriggerKind
from Licode.compact.compact import manage_context
from Licode.conversation import Conversation
from Licode.llm import Message, StreamEvent, ToolResult

from .conftest import FakeCompactProvider, make_input, summary_text


@pytest.mark.asyncio
async def test_auto_triggers_only_after_threshold(tmp_path: Path) -> None:
    below = Conversation()
    below.add_user("x" * 200000)
    below_provider = FakeCompactProvider([])
    await manage_context(
        make_input(
            tmp_path,
            below_provider,
            below,
            estimated=60000,
            context_window=100000,
        )
    )
    assert below_provider.requests == []

    above = Conversation()
    above.add_user("x" * 240000)
    above_provider = FakeCompactProvider(
        [[StreamEvent(text=summary_text()), StreamEvent(done=True)]]
    )
    await manage_context(
        make_input(
            tmp_path,
            above_provider,
            above,
            estimated=70000,
            context_window=100000,
        )
    )
    assert len(above_provider.requests) == 1


@pytest.mark.asyncio
async def test_auto_uses_layer1_reduced_size_before_threshold(tmp_path: Path) -> None:
    conversation = Conversation()
    conversation.replace_history(
        [
            Message(
                role="tool",
                tool_results=[ToolResult("large", "x" * 240000)],
            )
        ]
    )
    provider = FakeCompactProvider([])
    await manage_context(
        make_input(
            tmp_path,
            provider,
            conversation,
            estimated=70000,
            context_window=100000,
        )
    )
    assert provider.requests == []
    assert "[content offloaded]" in conversation.messages()[0].tool_results[0].content


@pytest.mark.asyncio
async def test_manual_bypasses_threshold_and_circuit_breaker(tmp_path: Path) -> None:
    conversation = Conversation()
    conversation.add_user("很短")
    tracking = CompactCircuitBreaker()
    for _ in range(3):
        tracking.record_failure()
    provider = FakeCompactProvider([[StreamEvent(text=summary_text()), StreamEvent(done=True)]])
    output = await manage_context(
        make_input(
            tmp_path,
            provider,
            conversation,
            trigger=TriggerKind.MANUAL,
            estimated=500,
            tracking=tracking,
        )
    )
    assert output.before_tokens == 500
    assert len(provider.requests) == 1
    assert provider.requests[0].tools is None
    assert tracking.tripped()


@pytest.mark.asyncio
async def test_emergency_runs_layer1_before_summary(tmp_path: Path) -> None:
    conversation = Conversation()
    conversation.replace_history(
        [
            Message(
                role="tool",
                tool_results=[ToolResult("large", "x" * 60000)],
            )
        ]
    )
    provider = FakeCompactProvider([[StreamEvent(text=summary_text()), StreamEvent(done=True)]])
    input_ = make_input(
        tmp_path,
        provider,
        conversation,
        trigger=TriggerKind.EMERGENCY,
        estimated=20000,
    )
    await manage_context(input_)
    assert (Path(input_.session.spill_dir) / "large").stat().st_size == 60000
    assert "[content offloaded]" in provider.requests[0].messages[0].content


@pytest.mark.asyncio
async def test_auto_failures_trip_and_success_resets(tmp_path: Path) -> None:
    tracking = CompactCircuitBreaker()
    conversation = Conversation()
    conversation.add_user("x" * 240000)
    provider = FakeCompactProvider(
        [[StreamEvent(err=RuntimeError(f"失败{index}"))] for index in range(3)]
    )
    replacement = ContentReplacementState()
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await manage_context(
                make_input(
                    tmp_path,
                    provider,
                    conversation,
                    estimated=70000,
                    context_window=100000,
                    tracking=tracking,
                    replacement=replacement,
                )
            )
    assert tracking.tripped()

    skipped = FakeCompactProvider([])
    await manage_context(
        make_input(
            tmp_path,
            skipped,
            conversation,
            estimated=70000,
            context_window=100000,
            tracking=tracking,
            replacement=replacement,
        )
    )
    assert skipped.requests == []


@pytest.mark.asyncio
async def test_too_small_context_window_skips_auto_summary(tmp_path: Path) -> None:
    conversation = Conversation()
    conversation.add_user("x" * 100000)
    provider = FakeCompactProvider([])
    await manage_context(
        make_input(
            tmp_path,
            provider,
            conversation,
            estimated=30000,
            context_window=33000,
        )
    )
    assert provider.requests == []
