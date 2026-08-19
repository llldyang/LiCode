from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from Licode.agent import Agent
from Licode.agent.team_hook import IncomingMessage, TeammateContext
from Licode.conversation import Conversation
from Licode.llm import Request, StreamEvent
from Licode.permission import Engine, Mode
from Licode.team import BackendType
from Licode.tool import Registry, Result


class FakeProvider:
    def __init__(self, script: list[StreamEvent]) -> None:
        self.script = script
        self.requests: list[Request] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake"

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        for event in self.script:
            yield event


class SendMessageProbe:
    read_only = False
    is_system = False

    def name(self) -> str:
        return "SendMessage"

    def description(self) -> str:
        return "发送计划"

    def parameters(self):
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        return Result(args)


@pytest.mark.asyncio
async def test_incoming_mail_is_injected_and_plan_approval_switches_mode(tmp_path: Path) -> None:
    unread = [
        IncomingMessage(
            "lead",
            "plan_approval_response",
            "plan approved",
            "继续执行",
            123,
            {"approve": True},
        )
    ]
    marked: list[int] = []

    async def read_unread():
        return [0], unread

    async def mark_read(indices: list[int]) -> None:
        marked.extend(indices)

    context = TeammateContext(
        "demo",
        "planner",
        "agent-1",
        BackendType.IN_PROCESS,
        str(tmp_path),
        read_unread,
        mark_read,
    )
    registry = Registry()
    registry.register(SendMessageProbe())
    provider = FakeProvider([StreamEvent(text="继续"), StreamEvent(done=True)])
    agent = Agent(
        provider,
        registry,
        "test",
        Engine(root=str(tmp_path)),
        permission_mode=Mode.PLAN,
        team_context=context,
    )
    conversation = Conversation()
    conversation.add_user("等待审批")

    _ = [event async for event in agent.run(conversation, Mode.PLAN, asyncio.Event())]

    assert agent.permission_mode is Mode.DEFAULT
    assert marked == [0]
    assert "<incoming-messages>" in provider.requests[0].reminder
    assert "权限模式已切到 default" in provider.requests[0].reminder
    assert [tool.name for tool in provider.requests[0].tools or []] == ["SendMessage"]
