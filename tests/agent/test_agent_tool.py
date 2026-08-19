import asyncio
import json

import pytest

from Licode.agent import AgentTool, Event
from Licode.agent.context import reset_execution_context, set_execution_context
from Licode.conversation import Conversation
from Licode.llm import Message, StreamEvent
from Licode.subagent import Catalog, Definition
from Licode.task import Manager

from .test_run_to_completion import FakeProvider, agent_for


class MockCatalog:
    def __init__(self) -> None:
        self.definition = Definition("worker", "测试 worker")

    def resolve(self, name: str):
        return self.definition if name == "worker" else None

    def fork_definition(self):
        return Catalog().fork_definition()

    def list(self):
        return [self.definition]


class StubAgent:
    async def run_to_completion(self, conv, task, events=None):
        if task:
            conv.add_user(task)
        if events is not None:
            await events.put(Event(text="stub"))
        return "stub-result"


class CancelProbeAgent:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cleaned = asyncio.Event()

    async def run_to_completion(self, conv, task, events=None):
        del conv, task, events
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cleaned.set()


def make_tool(tmp_path, *, bg_enabled=True):
    parent = agent_for(tmp_path, FakeProvider([[StreamEvent(text="unused")]]))
    return AgentTool(MockCatalog(), Manager(), parent, bg_enabled), parent


@pytest.mark.asyncio
async def test_basic_and_missing_prompt(tmp_path) -> None:
    tool, _ = make_tool(tmp_path)
    assert tool.name() == "Agent"
    assert set(tool.parameters()["properties"]) == {
        "prompt",
        "description",
        "subagent_type",
        "model",
        "run_in_background",
        "name",
    }
    result = await tool.execute('{"description":"x"}')
    assert result.is_error and "prompt is required" in result.content


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"prompt": 1, "description": "x"},
        {"prompt": "x", "description": "x", "run_in_background": "yes"},
        {"prompt": "x", "description": "x", "extra": True},
    ],
)
async def test_schema_types_are_enforced(tmp_path, payload) -> None:
    tool, _ = make_tool(tmp_path)
    result = await tool.execute(json.dumps(payload))
    assert result.is_error


@pytest.mark.asyncio
async def test_unknown_type(tmp_path) -> None:
    tool, _ = make_tool(tmp_path)
    result = await tool.execute(
        json.dumps({"prompt": "x", "description": "x", "subagent_type": "missing"})
    )
    assert result.is_error and "unknown subagent_type" in result.content


@pytest.mark.asyncio
async def test_foreground_returns_final_text(tmp_path, monkeypatch) -> None:
    tool, _ = make_tool(tmp_path)
    monkeypatch.setattr(tool, "_new_sub_agent", lambda definition, allowed: StubAgent())
    result = await tool.execute(
        json.dumps({"prompt": "x", "description": "x", "subagent_type": "worker"})
    )
    assert not result.is_error
    assert result.content == "stub-result"


@pytest.mark.asyncio
async def test_background_launches(tmp_path, monkeypatch) -> None:
    tool, _ = make_tool(tmp_path)
    monkeypatch.setattr(tool, "_new_sub_agent", lambda definition, allowed: StubAgent())
    result = await tool.execute(
        json.dumps(
            {
                "prompt": "x",
                "description": "x",
                "subagent_type": "worker",
                "run_in_background": True,
            }
        )
    )
    payload = json.loads(result.content)
    assert payload["status"] == "async_launched"
    await asyncio.wait_for(tool.task_mgr.subscribe_done().get(), 1)


@pytest.mark.asyncio
async def test_nested_and_fork_context_are_blocked(tmp_path) -> None:
    tool, parent = make_tool(tmp_path)
    child = agent_for(tmp_path, FakeProvider([[StreamEvent(text="unused")]]), is_sub_agent=True)
    conversation = Conversation()
    tokens = set_execution_context(child, conversation)
    try:
        nested = await tool.execute(
            json.dumps({"prompt": "x", "description": "x", "subagent_type": "worker"})
        )
    finally:
        reset_execution_context(tokens)
    assert nested.is_error and "SubAgent" in nested.content

    forked = Conversation.from_messages(
        [Message(role="user", content="<fork_boilerplate>fork</fork_boilerplate>")]
    )
    tokens = set_execution_context(parent, forked)
    try:
        fork_result = await tool.execute(
            json.dumps({"prompt": "x", "description": "x", "subagent_type": "worker"})
        )
    finally:
        reset_execution_context(tokens)
    assert fork_result.is_error and "Fork 子 Agent" in fork_result.content


@pytest.mark.asyncio
async def test_background_disabled_rejects_fork(tmp_path) -> None:
    tool, _ = make_tool(tmp_path, bg_enabled=False)
    result = await tool.execute(json.dumps({"prompt": "x", "description": "x"}))
    assert result.is_error and "background mode is disabled" in result.content


def test_child_inherits_parent_context_window(tmp_path) -> None:
    tool, parent = make_tool(tmp_path)
    parent.runtime.context_window = 98765
    child = tool._new_sub_agent(tool.catalog.resolve("worker"), [])
    assert child.runtime.context_window == 98765


@pytest.mark.asyncio
async def test_foreground_cancellation_waits_for_child_cleanup(tmp_path, monkeypatch) -> None:
    tool, _ = make_tool(tmp_path)
    probe = CancelProbeAgent()
    monkeypatch.setattr(tool, "_new_sub_agent", lambda definition, allowed: probe)
    running = asyncio.create_task(
        tool.execute(json.dumps({"prompt": "x", "description": "x", "subagent_type": "worker"}))
    )
    await probe.started.wait()

    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert probe.cleaned.is_set()
