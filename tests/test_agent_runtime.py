from Licode.agent import SessionRuntime
from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)


async def test_reset_for_new_session_resets_all_session_state(tmp_path) -> None:
    first = new_session_context(str(tmp_path))
    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=first,
        context_window=123456,
        turn_count=8,
        usage_anchor=20,
        anchor_msg_len=4,
    )
    runtime.recovery.record_file(str(tmp_path / "old.txt"), "old")
    runtime.auto_tracking.record_failure()
    second = new_session_context(str(tmp_path))

    runtime.append_reminders(["old reminder"])
    await runtime.reset_for_new_session(second)

    assert runtime.session is second
    assert runtime.context_window == 123456
    assert runtime.turn_count == 0
    assert runtime.usage_anchor == 0
    assert runtime.anchor_msg_len == 0
    assert runtime.replacement.replacement_count() == 0
    assert runtime.recovery.snapshot() == []
    assert not runtime.auto_tracking.tripped()
    assert runtime.take_reminders() == []


def test_pending_reminders_are_taken_once(tmp_path) -> None:
    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(str(tmp_path)),
    )
    runtime.append_reminders(["first", "second"])
    assert runtime.take_reminders() == ["first", "second"]
    assert runtime.take_reminders() == []
