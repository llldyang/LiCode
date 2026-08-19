import asyncio

import pytest

from Licode.hook import Event, is_blocking
from Licode.hook.engine import Engine
from Licode.hook.executor import ExecutionResult
from Licode.hook.rule import Action, ActionType, PromptAction, Rule


class FakeExecutor:
    def __init__(self, outcomes: dict[str, ExecutionResult] | None = None) -> None:
        self.outcomes = outcomes or {}
        self.calls: list[tuple[str, dict, bool]] = []
        self.started = asyncio.Event()

    async def run(self, rule: Rule, payload: dict, *, blocking: bool) -> ExecutionResult:
        self.calls.append((rule.name, payload, blocking))
        self.started.set()
        return self.outcomes.get(rule.name, ExecutionResult())

    async def close(self) -> None:
        return None


class ControlledExecutor(FakeExecutor):
    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()
        self.results: asyncio.Queue[ExecutionResult | Exception] = asyncio.Queue()

    async def run(self, rule: Rule, payload: dict, *, blocking: bool) -> ExecutionResult:
        self.calls.append((rule.name, payload, blocking))
        self.started.set()
        await self.release.wait()
        result = await self.results.get()
        if isinstance(result, Exception):
            raise result
        return result


def rule(
    name: str,
    event: Event = Event.PRE_TOOL_USE,
    *,
    once: bool = False,
    background: bool = False,
) -> Rule:
    return Rule(
        name,
        event,
        Action(ActionType.PROMPT, prompt=PromptAction(name)),
        only_once=once,
        asyncio_mode=background,
    )


def test_all_events_and_blocking_set() -> None:
    assert len(Event) == 11
    assert is_blocking(Event.PRE_TOOL_USE)
    assert is_blocking(Event.USER_PROMPT_SUBMIT)
    assert not is_blocking(Event.STOP)


@pytest.mark.asyncio
async def test_dispatch_order_prompt_and_first_block_stops_later() -> None:
    fake = FakeExecutor(
        {
            "first": ExecutionResult(prompt="remember"),
            "block": ExecutionResult(blocked=True, reason="denied"),
        }
    )
    engine = Engine([rule("first"), rule("block"), rule("last")], [], fake)  # type: ignore[arg-type]

    result = await engine.dispatch(Event.PRE_TOOL_USE, {"tool_name": "write_file"})

    assert [call[0] for call in fake.calls] == ["first", "block"]
    assert result.injected_prompts == ["remember"]
    assert result.blocked and result.blocking_hook_name == "block" and result.reason == "denied"
    assert fake.calls[0][1]["event"] == "PreToolUse"


@pytest.mark.asyncio
async def test_only_once_and_reset() -> None:
    fake = FakeExecutor()
    engine = Engine([rule("once", Event.STOP, once=True)], [], fake)  # type: ignore[arg-type]
    await engine.dispatch(Event.STOP, {})
    await engine.dispatch(Event.STOP, {})
    assert len(fake.calls) == 1
    await engine.reset_for_new_session()
    await engine.dispatch(Event.STOP, {})
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_only_once_is_isolated_by_session_id() -> None:
    fake = FakeExecutor()
    engine = Engine([rule("once", Event.STOP, once=True)], [], fake)  # type: ignore[arg-type]
    await engine.dispatch(Event.STOP, {"session_id": "parent"})
    await engine.dispatch(Event.STOP, {"session_id": "parent"})
    await engine.dispatch(Event.STOP, {"session_id": "child"})
    assert len(fake.calls) == 2

    await engine.reset_for_new_session("parent")
    await engine.dispatch(Event.STOP, {"session_id": "parent"})
    await engine.dispatch(Event.STOP, {"session_id": "child"})
    assert len(fake.calls) == 3


@pytest.mark.asyncio
async def test_async_rule_runs_in_background_and_logs_error(capsys) -> None:
    fake = FakeExecutor({"async": ExecutionResult(err=RuntimeError("boom"))})
    engine = Engine([rule("async", Event.STOP, background=True)], [], fake)  # type: ignore[arg-type]
    result = await engine.dispatch(Event.STOP, {})
    assert not result.blocked and result.injected_prompts == []
    await engine.wait_background()
    assert fake.started.is_set()
    assert "[hook async] Stop failed: boom" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_only_once_is_claimed_atomically_and_only_consumed_on_success(capsys) -> None:
    fake = ControlledExecutor()
    engine = Engine(
        [rule("once", Event.STOP, once=True, background=True)],
        [],
        fake,  # type: ignore[arg-type]
    )

    await engine.dispatch(Event.STOP, {})
    await fake.started.wait()
    await engine.dispatch(Event.STOP, {})
    assert len(fake.calls) == 1

    await fake.results.put(RuntimeError("first failed"))
    fake.release.set()
    await engine.wait_background()
    assert "[hook once] Stop failed: first failed" in capsys.readouterr().err

    fake.started.clear()
    fake.release.clear()
    await fake.results.put(ExecutionResult())
    await engine.dispatch(Event.STOP, {})
    await fake.started.wait()
    fake.release.set()
    await engine.wait_background()
    await engine.dispatch(Event.STOP, {})
    assert len(fake.calls) == 2


@pytest.mark.asyncio
async def test_sync_executor_exception_is_logged_and_later_rule_continues(capsys) -> None:
    class RaisingExecutor(FakeExecutor):
        async def run(self, rule: Rule, payload: dict, *, blocking: bool) -> ExecutionResult:
            self.calls.append((rule.name, payload, blocking))
            if rule.name == "broken":
                raise RuntimeError("unexpected")
            return ExecutionResult(prompt="continued")

    fake = RaisingExecutor()
    engine = Engine(
        [rule("broken", Event.STOP), rule("later", Event.STOP)],
        [],
        fake,  # type: ignore[arg-type]
    )

    result = await engine.dispatch(Event.STOP, {})

    assert [call[0] for call in fake.calls] == ["broken", "later"]
    assert result.injected_prompts == ["continued"]
    assert "[hook broken] Stop failed: unexpected" in capsys.readouterr().err
