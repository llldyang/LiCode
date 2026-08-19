from __future__ import annotations

import json
from pathlib import Path

import pytest

from Licode.task import Manager as TaskManager
from Licode.team import AgentNameRegistry, BackendType, Manager, TeammateInfo
from Licode.team.mailbox import Box
from Licode.team.tools import (
    SendMessageTool,
    TaskCreateTool,
    TaskGetTool,
    TaskListTool,
    TaskUpdateTool,
    TeamCreateTool,
)


@pytest.mark.asyncio
async def test_team_and_shared_task_tools(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("Licode.team.manager.detect", lambda: BackendType.IN_PROCESS)
    task_mgr = TaskManager()
    manager = Manager(tmp_path, tmp_path, None, task_mgr, AgentNameRegistry())
    created = await TeamCreateTool(manager).execute(
        json.dumps({"team_name": "demo team", "description": "协作"})
    )
    assert json.loads(created.content)["team_name"] == "demo-team"

    first = await TaskCreateTool(manager).execute(json.dumps({"title": "基础"}))
    first_id = json.loads(first.content)["task_id"]
    second = await TaskCreateTool(manager).execute(json.dumps({"title": "后续"}))
    second_id = json.loads(second.content)["task_id"]
    updated = await TaskUpdateTool(manager).execute(
        json.dumps({"task_id": second_id, "add_blocked_by": [first_id]})
    )
    assert first_id in json.loads(updated.content)["blocked_by"]
    listed = await TaskListTool(manager).execute(json.dumps({"status": "pending"}))
    assert len(json.loads(listed.content)) == 2
    fetched = await TaskGetTool(manager).execute(json.dumps({"task_id": first_id}))
    assert second_id in json.loads(fetched.content)["blocks"]


@pytest.mark.asyncio
async def test_send_message_unicast_and_broadcast(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("Licode.team.manager.detect", lambda: BackendType.IN_PROCESS)
    task_mgr = TaskManager()
    registry = AgentNameRegistry()
    manager = Manager(tmp_path, tmp_path, None, task_mgr, registry)
    team = await manager.create("demo", "")
    await team.add_member(
        TeammateInfo(
            name="alice",
            agent_id="agent-1",
            backend_type=BackendType.IN_PROCESS,
            is_active=True,
        )
    )
    registry.register("alice", "agent-1")
    tool = SendMessageTool(manager)

    result = await tool.execute(json.dumps({"to": "alice", "summary": "hello", "message": "正文"}))
    assert json.loads(result.content)["delivered_to"] == ["agent-1"]
    assert (await Box(team.mailbox_dir).read("agent-1"))[0].content == "正文"

    registry.unregister("alice")
    by_id = await tool.execute(
        json.dumps({"to": "agent-1", "summary": "direct id", "message": "按 ID 投递"})
    )
    assert json.loads(by_id.content)["delivered_to"] == ["agent-1"]

    broadcast = await tool.execute(
        json.dumps({"to": "*", "summary": "all members", "message": "广播"})
    )
    assert json.loads(broadcast.content)["delivered_to"] == ["agent-1"]
