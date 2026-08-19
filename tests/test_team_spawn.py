from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import pytest

from Licode.agent import Agent, AgentTool, SessionRuntime
from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from Licode.conversation import Conversation
from Licode.llm import Request, StreamEvent, ToolCall
from Licode.permission import Engine
from Licode.subagent import load_catalog
from Licode.task import Manager as TaskManager
from Licode.team import AgentNameRegistry, BackendType, Manager
from Licode.team.mailbox import Box
from Licode.team.tools import SendMessageTool
from Licode.tool import new_default_registry
from Licode.worktree import Worktree


class ScriptedProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.requests: list[Request] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        self.calls += 1
        if self.calls == 1:
            yield StreamEvent(
                tool_calls=[
                    ToolCall(
                        "write-1",
                        "write_file",
                        json.dumps({"path": "team-output.txt", "content": "step1\n"}),
                    )
                ]
            )
        elif self.calls == 2:
            yield StreamEvent(text="第一轮完成")
        else:
            yield StreamEvent(text="续派完成")
        yield StreamEvent(done=True)


class FakeWorktreeManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.removed: list[str] = []

    async def create(self, name: str, base_ref: str, manual: bool) -> Worktree:
        del base_ref, manual
        path = self.root / "worktrees" / name.replace("/", "+")
        path.mkdir(parents=True)
        return Worktree(
            name,
            str(path),
            f"worktree-{name.replace('/', '+')}",
            "head",
            "head",
            datetime.now(),
            False,
        )

    async def remove(self, name: str, opts) -> None:
        del opts
        self.removed.append(name)


async def wait_until(predicate, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_inprocess_spawn_worktree_idle_and_resume(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("Licode.team.manager.detect", lambda: BackendType.IN_PROCESS)
    name_registry = AgentNameRegistry()
    task_mgr = TaskManager(name_registry)
    worktrees = FakeWorktreeManager(tmp_path)
    team_mgr = Manager(tmp_path, tmp_path, worktrees, task_mgr, name_registry)  # type: ignore[arg-type]
    team = await team_mgr.create("demo", "")
    registry = new_default_registry()
    send_message = SendMessageTool(team_mgr)
    registry.register(send_message)
    provider = ScriptedProvider()
    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(str(tmp_path)),
    )
    parent = Agent(provider, registry, "test", Engine(root=str(tmp_path)), runtime=runtime)
    catalog = load_catalog(str(tmp_path))
    agent_tool = AgentTool(catalog, task_mgr, parent, True, team_hook=team_mgr)
    registry.register(agent_tool)
    team_mgr.configure_spawn(agent_tool, object())
    task_mgr.on_task_done(team_mgr.handle_task_done)

    spawned = await agent_tool.execute(
        json.dumps(
            {
                "team_name": "demo",
                "name": "bob",
                "subagent_type": "general-purpose",
                "description": "写测试文件",
                "prompt": "在 Worktree 写入文件",
            }
        )
    )
    assert not spawned.is_error
    payload = json.loads(spawned.content)
    task_id = payload["agent_id"]
    output_path = Path(payload["worktree"], "team-output.txt")
    await wait_until(output_path.is_file)
    assert f"你的 agent_id: {task_id}" in provider.requests[0].reminder
    assert "bob(general-purpose)" in provider.requests[0].reminder
    assert output_path.read_text(encoding="utf-8") == "step1\n"
    assert not (tmp_path / "team-output.txt").exists()
    await wait_until(lambda: team.member_by_name("bob").is_active is False)
    lead_messages = await Box(team.mailbox_dir).read("lead")
    assert any(message.summary == "bob idle" for message in lead_messages)
    background_task = task_mgr.get(task_id)
    assert background_task is not None
    assert background_task.sub_agent.dont_ask is True
    # 清空内存副本，验证续派确实从 session_dir 恢复历史。
    background_task.conv = Conversation()

    resumed = await send_message.execute(
        json.dumps({"to": "bob", "summary": "next task", "message": "继续第二轮"})
    )
    assert not resumed.is_error
    await wait_until(lambda: task_mgr.get(task_id).status.name == "COMPLETED")
    await wait_until(lambda: team.member_by_name("bob").is_active is False)
    assert provider.calls >= 3
    assert any(message.content == "第一轮完成" for message in provider.requests[-1].messages)

    await team_mgr.delete("demo", True)
    assert worktrees.removed == ["team-demo/bob"]
