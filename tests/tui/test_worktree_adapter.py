import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from Licode.agent import Event
from Licode.config import ProviderConfig
from Licode.permission import Engine
from Licode.tool import cwd_from_ctx, new_default_registry
from Licode.tui.app import LiCodeApp
from Licode.tui.worktree_adapter import WorktreeAdapter
from Licode.worktree import ExitReport, Worktree, WorktreeSession


def permission_engine(root: Path) -> Engine:
    return Engine(
        root=str(root.resolve()),
        local_path=str(root / ".Licode" / "settings.local.yaml"),
    )


def provider_config() -> ProviderConfig:
    return ProviderConfig(
        name="hidden-provider",
        protocol="openai",
        api_key="test-key",
        model="fake-model",
    )


class StubManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.worktree = Worktree(
            "demo",
            str(root / "demo"),
            "worktree-demo",
            "HEAD",
            "abc",
            datetime.now(),
            True,
        )
        self.session: WorktreeSession | None = None
        self.calls: list[tuple[object, ...]] = []

    async def create(self, name: str, base_ref: str, manual: bool) -> Worktree:
        self.calls.append(("create", name, base_ref, manual))
        return self.worktree

    def list(self) -> list[Worktree]:
        return [self.worktree]

    def current_session(self) -> WorktreeSession | None:
        return self.session

    async def enter(self, name: str) -> WorktreeSession:
        self.calls.append(("enter", name))
        self.session = WorktreeSession(
            str(self.root),
            self.worktree.path,
            name,
            "master",
            "abc",
            "session",
        )
        return self.session

    async def exit(self, name: str, action, opts) -> ExitReport:
        self.calls.append(("exit", name, str(action), opts.discard_changes))
        self.session = None
        return ExitReport(str(action) == "remove", self.worktree.path, self.worktree.branch)

    async def remove(self, name: str, opts) -> None:
        self.calls.append(("remove", name, opts.discard_changes))


class CwdAgent:
    def __init__(self) -> None:
        self.seen_cwd = ""

    async def run(self, conv, mode, cancel):
        del conv, mode, cancel
        self.seen_cwd = cwd_from_ctx() or ""
        yield Event(done=True)


@pytest.mark.asyncio
async def test_worktree_adapter_forwards_and_updates_cwd(tmp_path: Path) -> None:
    manager = StubManager(tmp_path)
    active = []
    adapter = WorktreeAdapter(manager, active.append)  # type: ignore[arg-type]
    assert await adapter.create("demo") == (manager.worktree.path, manager.worktree.branch)
    await adapter.enter("demo")
    assert active[-1] == manager.worktree.path
    assert adapter.list()[0].active
    assert await adapter.exit("remove", True)
    assert active[-1] == str(tmp_path)
    await adapter.remove("demo", True)
    assert ("remove", "demo", True) in manager.calls


@pytest.mark.asyncio
async def test_app_restores_and_injects_active_cwd(tmp_path: Path) -> None:
    manager = StubManager(tmp_path)
    await manager.enter("demo")
    app = LiCodeApp(
        [provider_config()],
        "test",
        new_default_registry(),
        permission_engine(tmp_path),
        worktree_mgr=manager,  # type: ignore[arg-type]
    )
    agent = CwdAgent()
    app.agent = agent  # type: ignore[assignment]
    app.turn_cancel = asyncio.Event()
    events = [event async for event in app.run_agent_events()]
    assert events[0].done
    assert app.active_cwd == manager.worktree.path
    assert app.cwd() == manager.worktree.path
    assert agent.seen_cwd == manager.worktree.path
