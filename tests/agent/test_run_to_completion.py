import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from Licode.agent import Agent, ApprovalRequest, Event, MaxTurnsReached, SessionRuntime
from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from Licode.conversation import Conversation
from Licode.llm import Request, StreamEvent, ToolCall
from Licode.permission import Mode, Outcome, new_engine
from Licode.tool import new_default_registry


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, responses: list[list[StreamEvent]]) -> None:
        self.responses = responses
        self.requests: list[Request] = []

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        for event in self.responses[len(self.requests) - 1]:
            yield event


def runtime(tmp_path: Path) -> SessionRuntime:
    return SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(str(tmp_path)),
    )


def agent_for(tmp_path: Path, provider: FakeProvider, **options) -> Agent:
    engine, error = new_engine(str(tmp_path))
    assert error is None
    return Agent(
        provider,
        new_default_registry(),
        "test",
        engine,
        runtime=runtime(tmp_path),
        **options,
    )


@pytest.mark.asyncio
async def test_one_turn_returns_text(tmp_path: Path) -> None:
    provider = FakeProvider([[StreamEvent(text="ok"), StreamEvent(done=True)]])
    conversation = Conversation()
    result = await agent_for(tmp_path, provider).run_to_completion(conversation, "任务")
    assert result == "ok"
    assert conversation.messages()[0].content == "任务"


@pytest.mark.asyncio
async def test_tool_then_text_and_events(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("hello", encoding="utf-8")
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[ToolCall("read", "read_file", json.dumps({"path": str(target)}))]
                ),
                StreamEvent(done=True),
            ],
            [StreamEvent(text="完成"), StreamEvent(done=True)],
        ]
    )
    events: asyncio.Queue = asyncio.Queue()
    result = await agent_for(tmp_path, provider).run_to_completion(Conversation(), "读取", events)
    observed = []
    while not events.empty():
        observed.append(events.get_nowait())
    assert result == "完成"
    assert any(isinstance(item, Event) and item.tool is not None for item in observed)
    assert any(isinstance(item, Event) and item.text == "完成" for item in observed)


@pytest.mark.asyncio
async def test_max_turns_raises(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("x", encoding="utf-8")
    responses = [
        [
            StreamEvent(
                tool_calls=[ToolCall(str(index), "read_file", json.dumps({"path": str(target)}))]
            ),
            StreamEvent(done=True),
        ]
        for index in range(3)
    ]
    with pytest.raises(MaxTurnsReached):
        await agent_for(tmp_path, FakeProvider(responses), max_turns=3).run_to_completion(
            Conversation(), "一直读取"
        )


@pytest.mark.asyncio
async def test_dont_ask_executes_write(tmp_path: Path) -> None:
    target = tmp_path / "created.txt"
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(
                            "write",
                            "write_file",
                            json.dumps({"path": str(target), "content": "ok"}),
                        )
                    ]
                )
            ],
            [StreamEvent(text="done")],
        ]
    )
    result = await agent_for(tmp_path, provider, dont_ask=True).run_to_completion(
        Conversation(), "写入"
    )
    assert result == "done"
    assert target.read_text(encoding="utf-8") == "ok"


@pytest.mark.asyncio
async def test_approval_upgrader_is_used(tmp_path: Path) -> None:
    target = tmp_path / "approved.txt"
    provider = FakeProvider(
        [
            [
                StreamEvent(
                    tool_calls=[
                        ToolCall(
                            "write",
                            "write_file",
                            json.dumps({"path": str(target), "content": "yes"}),
                        )
                    ]
                )
            ],
            [StreamEvent(text="done")],
        ]
    )
    requests: list[ApprovalRequest] = []

    async def upgrade(request: ApprovalRequest) -> tuple[Outcome, bool]:
        requests.append(request)
        return Outcome.ALLOW_ONCE, True

    result = await agent_for(
        tmp_path,
        provider,
        permission_mode=Mode.DEFAULT,
        approval_upgrader=upgrade,
    ).run_to_completion(Conversation(), "写入")
    assert result == "done"
    assert len(requests) == 1
    assert target.exists()
