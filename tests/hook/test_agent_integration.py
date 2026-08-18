import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from Licode.agent import Agent, ApprovalRequest, Phase, SessionRuntime
from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from Licode.conversation import Conversation
from Licode.hook import Event
from Licode.hook.engine import Engine as HookEngine
from Licode.hook.executor import ExecutionResult
from Licode.hook.rule import Action, ActionType, PromptAction, Rule
from Licode.llm import Request, StreamEvent, ToolCall
from Licode.permission import Engine as PermissionEngine
from Licode.permission import Mode, Outcome
from Licode.tool import Registry, Result


class FakeProvider:
    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.requests: list[Request] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        for event in self.scripts[len(self.requests) - 1]:
            yield event


class RecordingExecutor:
    def __init__(self, blocked_rule: str = "") -> None:
        self.blocked_rule = blocked_rule
        self.calls: list[tuple[str, Event, dict]] = []

    async def run(self, rule: Rule, payload: dict, *, blocking: bool) -> ExecutionResult:
        self.calls.append((rule.name, rule.event, payload))
        if rule.name == self.blocked_rule and blocking:
            return ExecutionResult(blocked=True, reason="blocked by hook")
        if rule.action.prompt is not None:
            return ExecutionResult(prompt=rule.action.prompt.text)
        return ExecutionResult()

    async def close(self) -> None:
        return None


class WriteProbe:
    read_only = False
    calls = 0

    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return "write"

    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        del args
        self.calls += 1
        return Result("written")


def prompt_rule(name: str, event: Event, text: str) -> Rule:
    return Rule(name, event, Action(ActionType.PROMPT, prompt=PromptAction(text)))


def runtime(tmp_path: Path) -> SessionRuntime:
    return SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(str(tmp_path)),
    )


def permission_engine(tmp_path: Path) -> PermissionEngine:
    return PermissionEngine(
        root=str(tmp_path.resolve()),
        local_path=str(tmp_path / ".Licode" / "settings.local.yaml"),
    )


def compact_summary() -> str:
    return (
        "<analysis>draft</analysis><summary>"
        + "\n".join(f"## {index} section" for index in range(1, 10))
        + "</summary>"
    )


@pytest.mark.asyncio
async def test_agent_injects_lifecycle_prompts_after_plan_reminder(tmp_path: Path) -> None:
    recorder = RecordingExecutor()
    hooks = HookEngine(
        [
            prompt_rule("pre-compact", Event.PRE_COMPACT, "PRE_COMPACT_REMINDER"),
            prompt_rule("post-compact", Event.POST_COMPACT, "POST_COMPACT_REMINDER"),
            prompt_rule("pre-user", Event.PRE_USER_MESSAGE, "PRE_USER_REMINDER"),
            prompt_rule("stop", Event.STOP, "STOP_REMINDER"),
        ],
        [],
        recorder,  # type: ignore[arg-type]
    )
    provider = FakeProvider([[StreamEvent(text="done"), StreamEvent(done=True)]])
    agent = Agent(
        provider,
        Registry(),
        "test",
        permission_engine(tmp_path),
        runtime=runtime(tmp_path),
        hook_engine=hooks,
    )
    conversation = Conversation()
    conversation.add_user("hello")

    outputs = [event async for event in agent.run(conversation, Mode.PLAN, asyncio.Event())]

    reminder = provider.requests[0].reminder
    positions = [
        reminder.index(value)
        for value in (
            "PLAN MODE",
            "PRE_COMPACT_REMINDER",
            "POST_COMPACT_REMINDER",
            "PRE_USER_REMINDER",
        )
    ]
    assert positions == sorted(positions)
    assert [call[1] for call in recorder.calls] == [
        Event.PRE_COMPACT,
        Event.POST_COMPACT,
        Event.PRE_USER_MESSAGE,
        Event.STOP,
    ]
    assert recorder.calls[-1][2]["iter"] == 1
    assert outputs[-1].done


@pytest.mark.asyncio
async def test_pre_tool_block_is_returned_to_model_and_post_tool_still_fires(
    tmp_path: Path,
) -> None:
    recorder = RecordingExecutor(blocked_rule="block-write")
    hooks = HookEngine(
        [
            prompt_rule("block-write", Event.PRE_TOOL_USE, ""),
            prompt_rule("after-write", Event.POST_TOOL_USE, ""),
        ],
        [],
        recorder,  # type: ignore[arg-type]
    )
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall("call-1", "write_file", json.dumps({"path": "blocked.txt"}))
                    ]
                ),
                StreamEvent(done=True),
            ],
            [StreamEvent(text="adjusted"), StreamEvent(done=True)],
        ]
    )
    registry = Registry()
    tool = WriteProbe()
    registry.register(tool)
    agent = Agent(
        provider,
        registry,
        "test",
        permission_engine(tmp_path),
        runtime=runtime(tmp_path),
        hook_engine=hooks,
    )
    conversation = Conversation()
    conversation.add_user("write it")

    outputs = [event async for event in agent.run(conversation, Mode.BYPASS, asyncio.Event())]

    assert tool.calls == 0
    tool_events = [event.tool for event in outputs if event.tool is not None]
    assert [event.phase for event in tool_events] == [Phase.START, Phase.END]
    assert tool_events[-1].is_error
    tool_result = provider.requests[1].messages[-1].tool_results[0]
    assert tool_result.is_error
    assert tool_result.content == "[hook block-write] blocked by hook"
    post_call = next(call for call in recorder.calls if call[1] is Event.POST_TOOL_USE)
    assert post_call[2]["is_error"] is True
    assert post_call[2]["tool_input"] == {"path": "blocked.txt"}


@pytest.mark.asyncio
async def test_notification_events_cover_approval_and_stream_error(tmp_path: Path) -> None:
    recorder = RecordingExecutor()
    hooks = HookEngine(
        [prompt_rule("notify", Event.NOTIFICATION, "")],
        [],
        recorder,  # type: ignore[arg-type]
    )
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall("call-1", "write_file", json.dumps({"path": "inside.txt"}))
                    ]
                )
            ],
            [StreamEvent(text="after denial"), StreamEvent(done=True)],
            [StreamEvent(err=RuntimeError("stream failed"))],
        ]
    )
    registry = Registry()
    registry.register(WriteProbe())
    agent = Agent(
        provider,
        registry,
        "test",
        permission_engine(tmp_path),
        runtime=runtime(tmp_path),
        hook_engine=hooks,
    )
    conversation = Conversation()
    conversation.add_user("write")

    async for output in agent.run(conversation, Mode.DEFAULT, asyncio.Event()):
        if isinstance(output, ApprovalRequest):
            output.respond.set_result(Outcome.DENY_ONCE)

    conversation.add_user("fail now")
    _ = [output async for output in agent.run(conversation, Mode.DEFAULT, asyncio.Event())]

    notifications = [call[2] for call in recorder.calls if call[1] is Event.NOTIFICATION]
    assert notifications[0]["kind"] == "approval"
    assert notifications[0]["detail"] == "write_file"
    assert notifications[1]["kind"] == "stream_error"
    assert "stream failed" in notifications[1]["detail"]


@pytest.mark.asyncio
async def test_manual_compact_emits_pre_and_post_events(tmp_path: Path) -> None:
    recorder = RecordingExecutor()
    hooks = HookEngine(
        [
            prompt_rule("pre", Event.PRE_COMPACT, ""),
            prompt_rule("post", Event.POST_COMPACT, ""),
        ],
        [],
        recorder,  # type: ignore[arg-type]
    )
    provider = FakeProvider([[StreamEvent(text=compact_summary()), StreamEvent(done=True)]])
    agent = Agent(
        provider,
        Registry(),
        "test",
        permission_engine(tmp_path),
        runtime=runtime(tmp_path),
        hook_engine=hooks,
    )
    conversation = Conversation()
    conversation.add_user("compact this")
    conversation.add_assistant("history")

    before, after = await agent.run_force_compact(conversation, [], Mode.DEFAULT)

    assert before >= 0 and after >= 0
    compact_calls = [
        call for call in recorder.calls if call[1] in {Event.PRE_COMPACT, Event.POST_COMPACT}
    ]
    assert [call[1] for call in compact_calls] == [Event.PRE_COMPACT, Event.POST_COMPACT]
    assert compact_calls[0][2]["trigger"] == "manual"
    assert compact_calls[1][2]["before_tokens"] == before
    assert compact_calls[1][2]["after_tokens"] == after
