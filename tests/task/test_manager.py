import asyncio

import pytest

from Licode.agent import ApprovalRequest, Event, Phase, ToolEvent, Usage
from Licode.conversation import Conversation
from Licode.task import CANCELLED, COMPLETED, FAILED, BackgroundTask, Manager, TaskBusy


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
    first_end = manager.get(task_id).end_time
    assert await manager.send_message("worker", "follow-up") == task_id
    running = manager.get(task_id)
    assert running is not None and running.end_time == 0
    assert running.start_time >= first_end
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


@pytest.mark.asyncio
async def test_finish_runner_waits_until_full_event_queue_is_drained() -> None:
    manager = Manager()
    task = BackgroundTask("task_test", "", FakeAgent(), Conversation(), "task")
    events: asyncio.Queue = asyncio.Queue(maxsize=1)
    await events.put(Event(text="queued"))
    release = asyncio.Event()

    async def aggregate_after_release() -> None:
        await release.wait()
        await manager._aggregate_task_events(events, task)

    async def finish() -> str:
        return "done"

    aggregator = asyncio.create_task(aggregate_after_release())
    handle = asyncio.create_task(finish())
    runner = asyncio.create_task(manager._finish_runner(task, events, handle, aggregator))
    await asyncio.sleep(0)
    assert not runner.done()
    release.set()
    await asyncio.wait_for(runner, 1)
    assert task.status is COMPLETED and task.result == "done"
    assert await manager.subscribe_done().get() == task.id


@pytest.mark.asyncio
async def test_cancelling_approval_upgrade_propagates_cancellation() -> None:
    manager = Manager()
    respond = asyncio.get_running_loop().create_future()
    request = ApprovalRequest("write_file", "{}", "needs approval", respond)
    upgrade = asyncio.create_task(manager.upgrade_approval(request))
    assert await manager.subscribe_approvals().get() is request

    upgrade.cancel()
    with pytest.raises(asyncio.CancelledError):
        await upgrade


@pytest.mark.asyncio
async def test_name_registry_and_done_callbacks() -> None:
    from Licode.team import AgentNameRegistry

    registry = AgentNameRegistry()
    manager = Manager(registry)
    called: list[str] = []

    async def on_done(task_id: str) -> None:
        called.append(task_id)

    manager.on_task_done(on_done)
    task_id = await manager.launch(FakeAgent(), Conversation(), "alice", "task")
    await asyncio.wait_for(manager.subscribe_done().get(), 1)
    for _ in range(10):
        if called:
            break
        await asyncio.sleep(0)
    assert registry.resolve("alice") == task_id
    assert called == [task_id]
