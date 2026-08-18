import json
from datetime import datetime
from pathlib import Path

import pytest

from Licode.agent import AgentTool
from Licode.agent.agent_worktree import build_worktree_notice, execute_with_worktree
from Licode.llm import StreamEvent
from Licode.subagent import Catalog, Definition
from Licode.task import Manager as TaskManager
from Licode.tool import cwd_from_ctx
from Licode.worktree import AutoCleanupReport, Worktree

from .test_run_to_completion import FakeProvider, agent_for


class StubManager:
    def __init__(self, path: Path, *, kept: bool) -> None:
        self.path = path
        self.kept = kept
        self.created: list[tuple[str, str, bool]] = []
        self.cleaned: list[str] = []

    async def create(self, name: str, base_ref: str, manual: bool) -> Worktree:
        self.created.append((name, base_ref, manual))
        return Worktree(
            name,
            str(self.path),
            f"worktree-{name}",
            base_ref,
            "abc",
            datetime.now(),
            manual,
        )

    async def auto_cleanup(self, name: str) -> AutoCleanupReport:
        self.cleaned.append(name)
        return AutoCleanupReport(self.kept, str(self.path), f"worktree-{name}")


class StubAgent:
    def __init__(self) -> None:
        self.cwd = ""
        self.task = ""

    async def run_to_completion(self, conv, task, events) -> str:
        del conv, events
        self.cwd = cwd_from_ctx() or ""
        self.task = task
        return "完成"


class IsolationCatalog:
    def __init__(self, *, background: bool = False) -> None:
        self.definition = Definition(
            "worker",
            "测试",
            background=background,
            isolation="worktree",
        )

    def resolve(self, name: str) -> Definition | None:
        return self.definition if name == "worker" else None

    def fork_definition(self) -> Definition:
        return Catalog().fork_definition()

    def list(self) -> list[Definition]:
        return [self.definition]


def test_build_worktree_notice() -> None:
    notice = build_worktree_notice("C:/parent", "C:/worktree")
    assert notice.startswith("<worktree-context>")
    assert notice.endswith("</worktree-context>")
    assert "C:/parent" in notice
    assert "C:/worktree" in notice


@pytest.mark.asyncio
async def test_execute_with_worktree_injects_cwd_and_cleans(tmp_path: Path) -> None:
    manager = StubManager(tmp_path, kept=False)
    agent = StubAgent()
    result = await execute_with_worktree(
        manager,  # type: ignore[arg-type]
        Definition("worker", "测试", isolation="worktree"),
        agent,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        "执行任务",
        object(),  # type: ignore[arg-type]
    )
    assert result == "完成"
    assert agent.cwd == str(tmp_path)
    assert "执行任务" in agent.task
    assert manager.created[0][1:] == ("HEAD", False)
    assert manager.cleaned == [manager.created[0][0]]


@pytest.mark.asyncio
async def test_execute_with_worktree_reports_kept_copy(tmp_path: Path) -> None:
    manager = StubManager(tmp_path, kept=True)
    result = await execute_with_worktree(
        manager,  # type: ignore[arg-type]
        Definition("worker", "测试", isolation="worktree"),
        StubAgent(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        "执行任务",
        object(),  # type: ignore[arg-type]
    )
    assert "Worktree 保留在" in result
    assert "worktree-agent-a" in result


@pytest.mark.asyncio
async def test_agent_tool_rejects_missing_worktree_manager(tmp_path: Path) -> None:
    parent = agent_for(tmp_path, FakeProvider([[StreamEvent(text="unused")]]))
    tool = AgentTool(IsolationCatalog(), TaskManager(), parent, True)
    result = await tool.execute(
        json.dumps({"prompt": "任务", "description": "测试", "subagent_type": "worker"})
    )
    assert result.is_error
    assert result.content == "worktree manager not configured"


@pytest.mark.asyncio
async def test_agent_tool_forces_isolated_background_to_foreground(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = agent_for(tmp_path, FakeProvider([[StreamEvent(text="unused")]]))
    manager = StubManager(tmp_path, kept=False)
    tool = AgentTool(
        IsolationCatalog(background=True),
        TaskManager(),
        parent,
        bg_enabled=False,
        worktree_mgr=manager,  # type: ignore[arg-type]
    )
    monkeypatch.setattr(tool, "_new_sub_agent", lambda definition, allowed: StubAgent())
    result = await tool.execute(
        json.dumps(
            {
                "prompt": "任务",
                "description": "测试",
                "subagent_type": "worker",
                "run_in_background": True,
            }
        )
    )
    assert not result.is_error
    assert result.content == "完成"
    assert manager.cleaned
