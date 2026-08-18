import re
import threading
from pathlib import Path

from Licode.compact import CompactCircuitBreaker, ContentReplacementState, RecoveryState
from Licode.compact.state import new_session_context, open_session_context, parse_session_time


def test_new_session_context_creates_unique_directories(tmp_path: Path) -> None:
    first = new_session_context(str(tmp_path))
    second = new_session_context(str(tmp_path))

    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", first.session_id)
    assert first.session_id != second.session_id
    assert Path(first.session_dir).is_dir()
    assert Path(first.spill_dir).is_dir()
    assert Path(second.spill_dir).is_dir()
    assert open_session_context(str(tmp_path), first.session_id) == first
    assert parse_session_time(first.session_id).strftime("%Y%m%d-%H%M%S") == first.session_id[:15]


def test_new_session_context_random_fallback(tmp_path: Path, monkeypatch) -> None:
    def fail(_: int) -> str:
        raise RuntimeError("随机源不可用")

    monkeypatch.setattr("Licode.compact.state.secrets.token_hex", fail)
    context = new_session_context(str(tmp_path))
    assert re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", context.session_id)


def test_decision_ledger_freezes_kept_replaced_and_retries_skip() -> None:
    state = ContentReplacementState()
    assert state.decide_once("kept", "原文", lambda: ("kept", "")) == "原文"
    assert state.decide_once("kept", "原文", lambda: ("replaced", "坏预览")) == "原文"

    assert state.decide_once("replaced", "大原文", lambda: ("replaced", "预览")) == "预览"
    assert state.decide_once("replaced", "大原文", lambda: ("kept", "")) == "预览"

    calls = 0

    def retry() -> tuple[str, str]:
        nonlocal calls
        calls += 1
        return "skip", ""

    state.decide_once("retry", "原文", retry)
    state.decide_once("retry", "原文", retry)
    assert calls == 2
    assert not state.has_decision("retry")


def test_recovery_snapshot_is_sorted_copied_and_thread_safe(tmp_path: Path) -> None:
    state = RecoveryState()
    barrier = threading.Barrier(51)

    def write(index: int) -> None:
        barrier.wait()
        state.record_file(str(tmp_path / f"{index}.txt"), str(index))
        state.snapshot()

    threads = [threading.Thread(target=write, args=(index,)) for index in range(50)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    snapshot = state.snapshot()
    assert len(snapshot) == 50
    assert snapshot == sorted(snapshot, key=lambda item: item.timestamp, reverse=True)
    snapshot.clear()
    assert len(state.snapshot()) == 50


def test_circuit_breaker_consecutive_failures_and_success_reset() -> None:
    breaker = CompactCircuitBreaker()
    breaker.record_failure()
    breaker.record_failure()
    assert not breaker.tripped()
    breaker.record_success()
    assert not breaker.tripped()
    for _ in range(3):
        breaker.record_failure()
    assert breaker.tripped()


def test_circuit_breaker_concurrent_access() -> None:
    breaker = CompactCircuitBreaker()
    barrier = threading.Barrier(31)

    def access(index: int) -> None:
        barrier.wait()
        if index % 3 == 0:
            breaker.record_success()
        else:
            breaker.record_failure()
        breaker.tripped()

    threads = [threading.Thread(target=access, args=(index,)) for index in range(30)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert isinstance(breaker.tripped(), bool)
