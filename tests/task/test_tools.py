import asyncio
import json

import pytest

from Licode.conversation import Conversation
from Licode.task import Manager, SendMessageTool, TaskGetTool, TaskListTool, TaskStopTool

from .test_manager import BlockingAgent, FakeAgent


@pytest.mark.asyncio
async def test_task_list_and_get() -> None:
    manager = Manager()
    task_id = await manager.launch(FakeAgent(), Conversation(), "worker", "task")
    await asyncio.wait_for(manager.subscribe_done().get(), 1)
    listed = await TaskListTool(manager).execute("{}")
    detail = await TaskGetTool(manager).execute(json.dumps({"task_id": task_id}))
    assert json.loads(listed.content)[0]["id"] == task_id
    assert json.loads(detail.content)["status"] == "completed"
    missing = await TaskGetTool(manager).execute('{"task_id":"missing"}')
    assert missing.is_error


@pytest.mark.asyncio
async def test_task_stop() -> None:
    manager = Manager()
    agent = BlockingAgent()
    task_id = await manager.launch(agent, Conversation(), "worker", "task")
    await agent.started.wait()
    result = await TaskStopTool(manager).execute(json.dumps({"task_id": task_id}))
    assert not result.is_error
    assert json.loads(result.content)["status"] == "cancellation_requested"
    await asyncio.wait_for(manager.subscribe_done().get(), 1)


@pytest.mark.asyncio
async def test_send_message_tool() -> None:
    manager = Manager()
    task_id = await manager.launch(FakeAgent(["one", "two"]), Conversation(), "w", "one")
    await asyncio.wait_for(manager.subscribe_done().get(), 1)
    result = await SendMessageTool(manager).execute(json.dumps({"name": "w", "message": "two"}))
    assert json.loads(result.content) == {"task_id": task_id, "status": "resumed"}
    await asyncio.wait_for(manager.subscribe_done().get(), 1)


def test_task_tools_are_system_tools() -> None:
    manager = Manager()
    tools = [
        TaskListTool(manager),
        TaskGetTool(manager),
        TaskStopTool(manager),
        SendMessageTool(manager),
    ]
    assert all(tool.is_system for tool in tools)
