import asyncio

import pytest

from Licode.agent import Event, Phase, ToolEvent, Usage
from Licode.conversation import Conversation
from Licode.task import CANCELLED, COMPLETED, FAILED, Manager, TaskBusy


class FakeAgent:
    def __init__(self, results: list[str] | None = None) -> None:
        self.results = results or ["ok"]
        self.calls = 0

    async def run_to_completion(self, conv, task, events=None):
        self.calls += 1
        if task:
            conv.add_user(task)
        if events is not None:
            await events.put(Event(tool=ToolEvent("read_file", phase=Phase.START)))
            await events.put(Event(usage=Usage(input=3, output=2)))
        return self.results[min(self.calls - 1, len(self.results) - 1)]


class FailingAgent:
    async def run_to_completion(self, conv, task, events=None):
        raise RuntimeError("boom")


class BlockingAgent:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run_to_completion(self, conv, task, events=None):
        self.started.set()
        await asyncio.Event().wait()
        return "unreachable"


@pytest.mark.asyncio
async def test_launch() -> None:
    manager = Manager()
    task_id = await manager.launch(FakeAgent(), Conversation(), "worker", "task")
    assert await asyncio.wait_for(manager.subscribe_done().get(), 1) == task_id
    task = manager.get(task_id)
    assert task is not None
    assert task.status is COMPLETED
    assert task.result == "ok"
    assert task.tool_count == 1
    assert task.usage.input == 3


@pytest.mark.asyncio
async def test_failure_is_captured() -> None:
    manager = Manager()
    task_id = await manager.launch(FailingAgent(), Conversation(), "", "task")
    await asyncio.wait_for(manager.subscribe_done().get(), 1)
    task = manager.get(task_id)
    assert task is not None and task.status is FAILED
    assert task.err is not None and "boom" in str(task.err)


@pytest.mark.asyncio
async def test_stop() -> None:
    manager = Manager()
    agent = BlockingAgent()
    task_id = await manager.launch(agent, Conversation(), "worker", "task")
    await asyncio.wait_for(agent.started.wait(), 1)
    assert await manager.stop(task_id)
    await asyncio.wait_for(manager.subscribe_done().get(), 1)
    task = manager.get(task_id)
    assert task is not None and task.status is CANCELLED


@pytest.mark.asyncio
async def test_send_message_reuses_completed_task() -> None:
    manager = Manager()
    conversation = Conversation()
    agent = FakeAgent(["first", "second"])
    task_id = await manager.launch(agent, conversation, "worker", "first task")
    await asyncio.wait_for(manager.subscribe_done().get(), 1)
    assert await manager.send_message("worker", "follow-up") == task_id
    await asyncio.wait_for(manager.subscribe_done().get(), 1)
    task = manager.get(task_id)
    assert task is not None and task.result == "second"
    assert conversation.messages()[-1].content == "follow-up"


@pytest.mark.asyncio
async def test_send_message_rejects_busy_and_name_uses_latest() -> None:
    manager = Manager()
    first = BlockingAgent()
    second = BlockingAgent()
    first_id = await manager.launch(first, Conversation(), "same", "one")
    second_id = await manager.launch(second, Conversation(), "same", "two")
    assert first_id != second_id
    with pytest.raises(TaskBusy):
        await manager.send_message("same", "next")
    await manager.stop(first_id)
    await manager.stop(second_id)
    for _ in range(2):
        await asyncio.wait_for(manager.subscribe_done().get(), 1)
