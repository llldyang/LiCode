import asyncio
import io
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from rich.console import Console
from textual.pilot import Pilot
from textual.widgets import Static

from Licode.config import ProviderConfig
from Licode.llm import Request, StreamEvent, ToolCall
from Licode.permission import Engine, Mode
from Licode.permission.rule import Rule
from Licode.prompt import EXECUTE_DIRECTIVE
from Licode.tool import new_default_registry
from Licode.tui.app import LiCodeApp, SessionState


class FakeProvider:
    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.call_count = 0

    @property
    def name(self) -> str:
        return "hidden-provider"

    @property
    def model(self) -> str:
        return "fake-model"

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        del req
        script = self.scripts[self.call_count]
        self.call_count += 1
        for event in script:
            await asyncio.sleep(0)
            yield event


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


def make_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: FakeProvider,
) -> LiCodeApp:
    monkeypatch.setattr("Licode.tui.app.new_provider", lambda config: provider)
    return LiCodeApp(
        [provider_config()],
        "test",
        new_default_registry(),
        permission_engine(tmp_path),
    )


def rendered_status(app: LiCodeApp) -> str:
    status = app.query_one("#statusbar", Static)
    output = io.StringIO()
    console = Console(file=output, width=120, color_system=None)
    console.print(status.content)
    return output.getvalue()


async def wait_for_state(pilot: Pilot[None], app: LiCodeApp, expected: SessionState) -> None:
    for _ in range(200):
        if app.state is expected:
            return
        await asyncio.sleep(0.01)
        await pilot.pause(0.01)
    raise AssertionError(f"TUI 未进入预期状态: {expected}")


@pytest.mark.asyncio
async def test_shift_tab_cycles_modes_status_and_keeps_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeProvider(
        [
            [StreamEvent(text="完成"), StreamEvent(done=True)],
            [StreamEvent(text="开始执行"), StreamEvent(done=True)],
        ]
    )
    app = make_app(tmp_path, monkeypatch, provider)
    app.engine.local.allow.append(Rule("Bash", "git status", True))
    expected = [
        (Mode.DEFAULT, "DEFAULT"),
        (Mode.ACCEPT_EDITS, "ACCEPT EDITS"),
        (Mode.PLAN, "PLAN"),
        (Mode.BYPASS, "BYPASS"),
        (Mode.DEFAULT, "DEFAULT"),
    ]

    async with app.run_test() as pilot:
        await pilot.pause()
        for index, (mode, label) in enumerate(expected):
            if index:
                before = len(app._transcript)
                await pilot.press("shift+tab")
                assert app.state is SessionState.IDLE
                assert len(app._transcript) == before + 1
                assert "已切换到" in app._transcript[-1].plain
            assert app.mode is mode
            status = rendered_status(app)
            assert label in status
            assert "hidden-provider" not in status
        assert [rule.render() for rule in app.engine.local.allow] == ["Bash(git status)"]

        await pilot.press("shift+tab")
        assert app.mode is Mode.ACCEPT_EDITS
        await app.submit("保持当前模式")
        assert app.mode is Mode.ACCEPT_EDITS
        await wait_for_state(pilot, app, SessionState.IDLE)
        assert app.mode is Mode.ACCEPT_EDITS

        await app.submit("/plan")
        assert app.mode is Mode.PLAN
        assert app.state is SessionState.IDLE
        await app.submit("/do")
        assert app.mode is Mode.DEFAULT
        assert app.conv.messages()[-1].content == EXECUTE_DIRECTIVE
        await wait_for_state(pilot, app, SessionState.IDLE)


@pytest.mark.asyncio
async def test_approval_menu_arrows_enter_and_number_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    targets = [tmp_path / f"choice-{index}.txt" for index in range(1, 4)]
    scripts: list[list[StreamEvent]] = []
    for index, target in enumerate(targets, start=1):
        call = ToolCall(
            f"write-{index}",
            "write_file",
            json.dumps({"path": str(target), "content": f"choice {index}"}),
        )
        scripts.extend(
            (
                [StreamEvent(tool_calls=[call]), StreamEvent(done=True)],
                [StreamEvent(text=f"第 {index} 次完成"), StreamEvent(done=True)],
            )
        )
    provider = FakeProvider(scripts)
    app = make_app(tmp_path, monkeypatch, provider)

    async with app.run_test() as pilot:
        await app.submit("使用方向键")
        await wait_for_state(pilot, app, SessionState.APPROVING)
        assert app.approve_cursor == 0
        assert app.query_one("#input").disabled
        approval_text = app.query_one("#streaming", Static).content
        output = io.StringIO()
        Console(file=output, width=120, color_system=None).print(approval_text)
        rendered = output.getvalue()
        assert "write_file" in rendered
        assert "需确认" in rendered
        assert "1. 允许本次" in rendered
        assert "2. 永久允许" in rendered
        assert "3. 拒绝本次" in rendered
        await pilot.press("down")
        assert app.approve_cursor == 1
        await pilot.press("enter")
        await wait_for_state(pilot, app, SessionState.IDLE)
        assert targets[0].read_text(encoding="utf-8") == "choice 1"
        local_settings = Path(app.engine.local_path).read_text(encoding="utf-8")
        assert "Write(choice-1.txt)" in local_settings

        await app.submit("使用数字一")
        await wait_for_state(pilot, app, SessionState.APPROVING)
        await pilot.press("1")
        await wait_for_state(pilot, app, SessionState.IDLE)
        assert targets[1].read_text(encoding="utf-8") == "choice 2"
        assert "Write(choice-2.txt)" not in Path(app.engine.local_path).read_text(encoding="utf-8")

        await app.submit("使用数字三")
        await wait_for_state(pilot, app, SessionState.APPROVING)
        await pilot.press("3")
        await wait_for_state(pilot, app, SessionState.IDLE)
        assert not targets[2].exists()
        assert provider.call_count == 6


@pytest.mark.asyncio
async def test_escape_cancels_approval_and_next_turn_still_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "cancelled.txt"
    call = ToolCall(
        "write-cancel",
        "write_file",
        json.dumps({"path": str(target), "content": "不应写入"}),
    )
    provider = FakeProvider(
        [
            [StreamEvent(tool_calls=[call]), StreamEvent(done=True)],
            [StreamEvent(tool_calls=[call]), StreamEvent(done=True)],
            [StreamEvent(text="取消后仍可继续"), StreamEvent(done=True)],
        ]
    )
    app = make_app(tmp_path, monkeypatch, provider)

    async with app.run_test() as pilot:
        await app.submit("触发审批后取消")
        await wait_for_state(pilot, app, SessionState.APPROVING)
        await pilot.press("escape")
        await wait_for_state(pilot, app, SessionState.IDLE)
        assert not target.exists()
        assert app.is_running
        assert app.query_one("#input").has_focus

        await app.submit("再次触发审批")
        await wait_for_state(pilot, app, SessionState.APPROVING)
        await pilot.press("ctrl+c")
        await wait_for_state(pilot, app, SessionState.IDLE)
        assert not target.exists()
        assert app.is_running
        assert app.query_one("#input").has_focus

        await app.submit("继续对话")
        await wait_for_state(pilot, app, SessionState.IDLE)
        assert app.conv.messages()[-1].content == "取消后仍可继续"
        assert provider.call_count == 3
