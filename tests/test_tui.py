import asyncio
import io
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from rich.console import Console
from textual.pilot import Pilot
from textual.widgets import OptionList, Static

from Licode.agent import CompactEvent, CompactPhase, SessionRuntime
from Licode.command import Command, Kind, Registry, register_builtins
from Licode.command.builtin_prompt import REVIEW_DIRECTIVE
from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from Licode.config import ProviderConfig
from Licode.hook import Event as HookEvent
from Licode.hook.engine import Engine as HookEngine
from Licode.hook.executor import ExecutionResult
from Licode.hook.rule import Action, ActionType, PromptAction
from Licode.hook.rule import Rule as HookRule
from Licode.llm import PromptTooLongError, Request, StreamEvent, ToolCall
from Licode.permission import Engine, Mode
from Licode.permission.matcher import compile_matcher
from Licode.permission.rule import Rule
from Licode.prompt import EXECUTE_DIRECTIVE
from Licode.session import Writer, list_sessions
from Licode.tool import new_default_registry
from Licode.tui.app import LiCodeApp, MessageInput, SessionState
from Licode.tui.complete import MAX_ROWS, CompletionMenu
from Licode.tui.view import format_compact_notice


class FakeProvider:
    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.call_count = 0
        self.requests: list[Request] = []

    @property
    def name(self) -> str:
        return "hidden-provider"

    @property
    def model(self) -> str:
        return "fake-model"

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
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
    hook_engine: HookEngine | None = None,
) -> LiCodeApp:
    monkeypatch.setattr("Licode.tui.app.new_provider", lambda config: provider)
    return LiCodeApp(
        [provider_config()],
        "test",
        new_default_registry(),
        permission_engine(tmp_path),
        hook_engine=hook_engine,
    )


class RecordingHookExecutor:
    def __init__(self, blocked_rule: str = "") -> None:
        self.blocked_rule = blocked_rule
        self.calls: list[tuple[str, HookEvent]] = []

    async def run(self, rule: HookRule, payload: dict, *, blocking: bool) -> ExecutionResult:
        del payload
        self.calls.append((rule.name, rule.event))
        if rule.name == self.blocked_rule and blocking:
            return ExecutionResult(blocked=True, reason="blocked by tui hook")
        if rule.action.prompt is not None:
            return ExecutionResult(prompt=rule.action.prompt.text)
        return ExecutionResult()

    async def close(self) -> None:
        return None


def hook_rule(
    name: str,
    event: HookEvent,
    text: str = "",
    *,
    once: bool = False,
    background: bool = False,
) -> HookRule:
    return HookRule(
        name,
        event,
        Action(ActionType.PROMPT, prompt=PromptAction(text)),
        only_once=once,
        asyncio_mode=background,
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


class ControlledProvider(FakeProvider):
    def __init__(self) -> None:
        super().__init__([])
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
        self.started.set()
        await self.release.wait()
        yield StreamEvent(text="**完成**")
        yield StreamEvent(done=True)


@pytest.mark.asyncio
async def test_basic_chat_input_is_disabled_until_stream_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ControlledProvider()
    app = make_app(tmp_path, monkeypatch, provider)

    async with app.run_test() as pilot:
        message_input = app.query_one("#input", MessageInput)
        message_input.text = "第一行"
        message_input.move_cursor((0, len(message_input.text)))
        await pilot.press("alt+enter")
        message_input.insert("第二行")
        assert message_input.text == "第一行\n第二行"

        await pilot.press("enter")
        await asyncio.wait_for(provider.started.wait(), timeout=1)
        assert app.state is SessionState.STREAMING
        assert message_input.text == ""
        assert message_input.disabled

        provider.release.set()
        await wait_for_state(pilot, app, SessionState.IDLE)
        assert not message_input.disabled
        assert provider.requests[0].messages[0].content == "第一行\n第二行"
        assert app.conv.messages()[-1].content == "**完成**"
        assert "完成于" in app._transcript[-1].renderables[-1].plain


@pytest.mark.asyncio
async def test_stream_error_restores_input_and_allows_next_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = RuntimeError("模拟鉴权失败")
    provider = FakeProvider(
        [
            [StreamEvent(err=failure)],
            [StreamEvent(text="恢复成功"), StreamEvent(done=True)],
        ]
    )
    app = make_app(tmp_path, monkeypatch, provider)

    async with app.run_test() as pilot:
        await app.submit("第一次")
        await wait_for_state(pilot, app, SessionState.IDLE)
        assert not app.query_one("#input", MessageInput).disabled
        assert any("模拟鉴权失败" in getattr(item, "plain", str(item)) for item in app._transcript)

        await app.submit("第二次")
        await wait_for_state(pilot, app, SessionState.IDLE)
        assert provider.call_count == 2
        assert app.conv.messages()[-1].content == "恢复成功"


@pytest.mark.asyncio
async def test_single_provider_enters_chat_and_multiple_providers_require_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    selected: list[ProviderConfig] = []
    fake_provider = FakeProvider([])

    def select_provider(config: ProviderConfig) -> FakeProvider:
        selected.append(config)
        return fake_provider

    monkeypatch.setattr("Licode.tui.app.new_provider", select_provider)
    single = LiCodeApp(
        [provider_config()],
        "test",
        new_default_registry(),
        permission_engine(tmp_path),
    )
    async with single.run_test() as pilot:
        await pilot.pause()
        assert single.state is SessionState.IDLE
        assert selected == [single.providers[0]]
        banner = str(single._transcript[0])
        assert "LiCode vtest" in banner
        assert "Ready for your request" in banner

    selected.clear()
    providers = [
        provider_config(),
        ProviderConfig("第二个", "anthropic", "test-key-2", "second-model"),
    ]
    multiple = LiCodeApp(
        providers,
        "test",
        new_default_registry(),
        permission_engine(tmp_path),
    )
    async with multiple.run_test() as pilot:
        await pilot.pause()
        choices = multiple.query_one("#provider-select", OptionList)
        assert multiple.state is SessionState.SELECTING
        assert choices.option_count == 2
        assert selected == []

        await pilot.press("down", "enter")
        assert multiple.state is SessionState.IDLE
        assert selected == [providers[1]]
        assert choices.styles.display == "none"


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
    app.engine.local.allow.append(
        Rule("Bash", compile_matcher("git status", is_command=True), True, "git status")
    )
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
            assert app.mode() is mode
            status = rendered_status(app)
            assert label in status
            assert "hidden-provider" not in status
        assert [rule.render() for rule in app.engine.local.allow] == ["Bash(git status)"]

        await pilot.press("shift+tab")
        assert app.mode() is Mode.ACCEPT_EDITS
        await app.submit("保持当前模式")
        assert app.mode() is Mode.ACCEPT_EDITS
        await wait_for_state(pilot, app, SessionState.IDLE)
        assert app.mode() is Mode.ACCEPT_EDITS

        await app.submit("/plan")
        assert app.mode() is Mode.PLAN
        assert app.state is SessionState.IDLE
        await app.submit("/do")
        assert app.mode() is Mode.DEFAULT
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


@pytest.mark.asyncio
async def test_compact_and_unknown_commands_do_not_enter_normal_chat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = "<analysis>草稿</analysis><summary>手动摘要</summary>"
    provider = FakeProvider([[StreamEvent(text=summary), StreamEvent(done=True)]])
    app = make_app(tmp_path, monkeypatch, provider)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.submit("/compact")
        assert provider.call_count == 1
        assert provider.scripts
        assert all("/compact" not in message.content for message in app.conv.messages())
        assert "已压缩，token 从" in app._transcript[-1].plain

        before = app.conv.length()
        await app.submit("/unknown")
        assert provider.call_count == 1
        assert app.conv.length() == before
        assert "未知命令" in app._transcript[-1].plain
        assert "/help" in app._transcript[-1].plain
        assert len(app.cmd_registry.visible()) == 15


@pytest.mark.asyncio
async def test_tui_dispatch_help_lists_all_builtins_without_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeProvider([])
    app = make_app(tmp_path, monkeypatch, provider)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.submit("/help")

        output = app._transcript[-1].plain
        lines = output.splitlines()
        assert len(lines) == 15
        assert [line.split()[0] for line in lines] == [
            f"/{command.name}" for command in app.cmd_registry.visible()
        ]
        assert provider.call_count == 0
        assert app.conv.length() == 0


@pytest.mark.asyncio
async def test_tui_dispatch_is_case_insensitive_and_unknown_is_friendly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeProvider([])
    app = make_app(tmp_path, monkeypatch, provider)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.submit("/Help")
        mixed_case = app._transcript[-1].plain
        await app.submit("/help")
        assert app._transcript[-1].plain == mixed_case

        before = app.conv.length()
        await app.submit("/foobar")
        assert "未知命令" in app._transcript[-1].plain
        assert "/help" in app._transcript[-1].plain
        assert app.conv.length() == before
        assert provider.call_count == 0


@pytest.mark.asyncio
async def test_tui_local_status_session_permission_and_memory_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeProvider([])
    app = make_app(tmp_path, monkeypatch, provider)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.submit("/status")
        status = app._transcript[-1].plain
        positions = [
            status.index(key)
            for key in ("Mode:", "Tokens:", "Tools:", "Memories:", "Model:", "Directory:")
        ]
        assert positions == sorted(positions)
        assert "6 enabled" in status

        await app.submit("/permission")
        assert app._transcript[-1].plain == "default"
        await app.submit("/memory")
        assert app._transcript[-1].plain == "无已加载的记忆文件"
        await app.submit("/session")
        assert "Session:" in app._transcript[-1].plain
        assert "Path:" in app._transcript[-1].plain
        assert provider.call_count == 0
        assert app.usage_in() == app.usage_out() == 0


@pytest.mark.asyncio
async def test_tui_only_local_commands_run_while_busy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeProvider([])
    app = make_app(tmp_path, monkeypatch, provider)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.state = SessionState.STREAMING
        await app.submit("/status")
        assert "Mode:" in app._transcript[-1].plain

        await app.submit("/plan")
        assert "请等待当前任务完成" in app._transcript[-1].plain
        assert app.mode() is Mode.DEFAULT
        assert app.state is SessionState.STREAMING


@pytest.mark.asyncio
async def test_tui_prompt_commands_inject_real_user_messages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeProvider(
        [
            [StreamEvent(text="执行完成"), StreamEvent(done=True)],
            [StreamEvent(text="审查完成"), StreamEvent(done=True)],
        ]
    )
    app = make_app(tmp_path, monkeypatch, provider)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.submit("/do")
        await wait_for_state(pilot, app, SessionState.IDLE)
        assert app.conv.messages()[0].content == EXECUTE_DIRECTIVE

        await app.submit("/review")
        await wait_for_state(pilot, app, SessionState.IDLE)
        assert app.conv.messages()[2].content == REVIEW_DIRECTIVE
        assert "审查" in app.conv.messages()[2].content
        assert provider.call_count == 2


@pytest.mark.asyncio
async def test_tui_clear_opens_new_session_and_keeps_old_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(str(tmp_path)),
    )
    writer = Writer(runtime.session.session_dir)
    provider = FakeProvider([])
    monkeypatch.setattr("Licode.tui.app.new_provider", lambda config: provider)
    app = LiCodeApp(
        [provider_config()],
        "test",
        new_default_registry(),
        permission_engine(tmp_path),
        runtime,
        writer,
    )
    old_id = runtime.session.session_id
    old_path = writer.path

    async with app.run_test() as pilot:
        await pilot.pause()
        app.conv.add_user("旧会话内容")
        app._usage_in = 100
        app._usage_out = 20
        await app.submit("/clear")

        assert app.runtime.session.session_id != old_id
        assert app.session_path() != old_path
        assert app.conv.length() == 0
        assert app.usage_in() == app.usage_out() == 0
        assert "开启新 session" in app._transcript[-1].plain
        assert Path(old_path).read_text(encoding="utf-8")
        assert old_id in {item.id for item in list_sessions(app.sessions_dir)}

    assert app.writer is not None
    app.writer.close()


@pytest.mark.asyncio
async def test_tui_session_start_prompt_reaches_first_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = RecordingHookExecutor()
    hooks = HookEngine(
        [hook_rule("zh-cn", HookEvent.SESSION_START, "SESSION_START_ZH_CN")],
        [str(tmp_path / ".LiCode" / "hooks.yaml")],
        recorder,  # type: ignore[arg-type]
    )
    provider = FakeProvider([[StreamEvent(text="中文回复"), StreamEvent(done=True)]])
    app = make_app(tmp_path, monkeypatch, provider, hooks)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.submit("hi there")
        await wait_for_state(pilot, app, SessionState.IDLE)

    assert "SESSION_START_ZH_CN" in provider.requests[0].reminder
    assert recorder.calls[0] == ("zh-cn", HookEvent.SESSION_START)


@pytest.mark.asyncio
async def test_tui_user_prompt_hook_blocks_and_preserves_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = RecordingHookExecutor(blocked_rule="warn-delete")
    hooks = HookEngine(
        [hook_rule("warn-delete", HookEvent.USER_PROMPT_SUBMIT)],
        [],
        recorder,  # type: ignore[arg-type]
    )
    provider = FakeProvider([])
    app = make_app(tmp_path, monkeypatch, provider, hooks)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.input_area.text = "please delete it"
        await app.submit(app.input_area.text)
        assert app.input_area.text == "please delete it"
        assert app.conv.length() == 0
        assert provider.call_count == 0
        assert "[hook warn-delete] blocked by tui hook" in app._transcript[-1].plain


@pytest.mark.asyncio
async def test_tui_clear_dispatches_session_events_and_resets_only_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = RecordingHookExecutor()
    hooks = HookEngine(
        [
            hook_rule("start-once", HookEvent.SESSION_START, once=True),
            hook_rule("end", HookEvent.SESSION_END),
        ],
        [],
        recorder,  # type: ignore[arg-type]
    )
    app = make_app(tmp_path, monkeypatch, FakeProvider([]), hooks)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.submit("/clear")

    assert recorder.calls == [
        ("start-once", HookEvent.SESSION_START),
        ("end", HookEvent.SESSION_END),
        ("start-once", HookEvent.SESSION_START),
    ]


@pytest.mark.asyncio
async def test_tui_quit_dispatches_session_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = RecordingHookExecutor()
    hooks = HookEngine(
        [hook_rule("end", HookEvent.SESSION_END)],
        [],
        recorder,  # type: ignore[arg-type]
    )
    app = make_app(tmp_path, monkeypatch, FakeProvider([]), hooks)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.action_quit()

    assert recorder.calls == [("end", HookEvent.SESSION_END)]


@pytest.mark.asyncio
async def test_hooks_command_groups_rules_and_prints_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = RecordingHookExecutor()
    source = str(tmp_path / ".LiCode" / "hooks.yaml")
    hooks = HookEngine(
        [
            hook_rule("start", HookEvent.SESSION_START, once=True),
            hook_rule("after", HookEvent.POST_TOOL_USE, background=True),
        ],
        [source],
        recorder,  # type: ignore[arg-type]
    )
    app = make_app(tmp_path, monkeypatch, FakeProvider([]), hooks)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.submit("/hooks")
        output = app._transcript[-1].plain

    assert "SessionStart:" in output and "start  SessionStart  prompt  [once]" in output
    assert "PostToolUse:" in output and "after  PostToolUse  prompt  [async]" in output
    assert f"Loaded from: {source}" in output


@pytest.mark.asyncio
async def test_tui_command_handler_exception_is_rendered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(ui) -> None:
        del ui
        raise RuntimeError("命令失败")

    app = make_app(tmp_path, monkeypatch, FakeProvider([]))
    app.cmd_registry.register(Command("broken", "失败命令", Kind.LOCAL, broken))

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.submit("/broken")
        assert "命令失败" in app._transcript[-1].plain


def test_completion_menu_filters_scrolls_and_handles_boundaries() -> None:
    app_registry = Registry()
    register_builtins(app_registry)
    menu = CompletionMenu()

    menu.update("/", app_registry)
    assert menu.active
    assert len(menu.items) == 15
    assert len(menu.render(120).splitlines()) <= MAX_ROWS

    menu.update("/s", app_registry)
    assert [item.name for item in menu.items] == ["session", "skill", "status"]
    menu.move_down()
    menu.move_down()
    assert menu.selected() is not None and menu.selected().name == "status"
    menu.move_up()
    menu.move_up()
    assert menu.selected() is not None and menu.selected().name == "session"

    menu.update("/missing", app_registry)
    assert menu.active and menu.selected() is None
    assert "无匹配" in menu.render(120)
    menu.update("/help\nnext", app_registry)
    assert not menu.active
    menu.update("hello", app_registry)
    assert not menu.active


@pytest.mark.asyncio
async def test_tui_completion_keys_execute_and_escape_preserves_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_app(tmp_path, monkeypatch, FakeProvider([]))

    async with app.run_test() as pilot:
        await pilot.pause()
        app.input_area.text = "/"
        await pilot.pause()
        assert app.completion.active and len(app.completion.items) == 15
        assert app.query_one("#completion", Static).styles.display == "block"

        app.input_area.text = "/s"
        await pilot.pause()
        assert [item.name for item in app.completion.items] == ["session", "skill", "status"]
        await pilot.press("down", "down", "enter")
        await pilot.pause()
        assert "Mode:" in app._transcript[-1].plain
        assert app.input_area.text == ""
        assert not app.completion.active

        app.input_area.text = "/s"
        await pilot.pause()
        await pilot.press("escape")
        assert app.input_area.text == "/s"
        assert not app.completion.active

        app.input_area.text = ""
        await pilot.pause()
        assert not app.completion.active

        app.input_area.text = "/s"
        await pilot.pause()
        await pilot.press("tab")
        await pilot.pause()
        assert "Session:" in app._transcript[-1].plain
        assert app.input_area.text == ""


@pytest.mark.asyncio
async def test_tui_zero_match_enter_runs_unknown_and_tab_only_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = make_app(tmp_path, monkeypatch, FakeProvider([]))

    async with app.run_test() as pilot:
        await pilot.pause()
        app.input_area.text = "/missing"
        await pilot.pause()
        before = len(app._transcript)
        await pilot.press("tab")
        assert not app.completion.active
        assert len(app._transcript) == before

        app.input_area.text = "/missing"
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert "未知命令" in app._transcript[-1].plain


def test_compact_notice_format_is_shared() -> None:
    assert (
        format_compact_notice(CompactEvent(phase=CompactPhase.BEFORE_AUTO)) == "正在压缩上下文..."
    )
    assert (
        format_compact_notice(CompactEvent(phase=CompactPhase.BEFORE_EMERGENCY))
        == "上下文撞墙，自动压缩中..."
    )
    assert (
        format_compact_notice(
            CompactEvent(phase=CompactPhase.AFTER_AUTO, before=167000, after=12000)
        )
        == "已压缩，token 从 167000 降至 12000"
    )
    assert "压缩失败" in format_compact_notice(
        CompactEvent(
            phase=CompactPhase.AFTER_EMERGENCY,
            err=RuntimeError("失败"),
        )
    )


@pytest.mark.asyncio
async def test_tui_renders_auto_compact_notices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = "<analysis>草稿</analysis><summary>自动摘要</summary>"
    provider = FakeProvider(
        [
            [StreamEvent(text=summary), StreamEvent(done=True)],
            [StreamEvent(text="完成"), StreamEvent(done=True)],
        ]
    )
    app = make_app(tmp_path, monkeypatch, provider)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.runtime.context_window = 60000
        for _ in range(10):
            app.conv.add_user("u" * 7000)
            app.conv.add_assistant("a" * 7000)
        await app.submit("继续")
        await wait_for_state(pilot, app, SessionState.IDLE)
        notices = [getattr(item, "plain", "") for item in app._transcript]
        assert "正在压缩上下文..." in notices
        assert any("已压缩，token 从" in notice for notice in notices)


@pytest.mark.asyncio
async def test_tui_renders_emergency_compact_notices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = "<analysis>草稿</analysis><summary>紧急摘要</summary>"
    provider = FakeProvider(
        [
            [StreamEvent(err=PromptTooLongError("过长"))],
            [StreamEvent(text=summary), StreamEvent(done=True)],
            [StreamEvent(text="重试完成"), StreamEvent(done=True)],
        ]
    )
    app = make_app(tmp_path, monkeypatch, provider)

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.submit("触发紧急压缩")
        await wait_for_state(pilot, app, SessionState.IDLE)
        notices = [getattr(item, "plain", "") for item in app._transcript]
        assert "上下文撞墙，自动压缩中..." in notices
        assert any("已压缩，token 从" in notice for notice in notices)
        assert provider.call_count == 3


@pytest.mark.asyncio
async def test_resume_search_cancel_restore_and_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions_dir = tmp_path / ".Licode" / "sessions"
    history_dir = sessions_dir / "20260817-120000-abcd"
    history_dir.mkdir(parents=True)
    old_ts = int(time.time()) - 7 * 60 * 60
    history_path = history_dir / "conversation.jsonl"
    history_path.write_text(
        "\n".join(
            json.dumps(entry, ensure_ascii=False)
            for entry in (
                {
                    "role": "user",
                    "content": "alpha 历史问题",
                    "model": "fake-model",
                    "ts": old_ts,
                },
                {"role": "assistant", "content": "历史回答", "ts": old_ts},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(str(tmp_path)),
    )
    current_writer = Writer(runtime.session.session_dir)
    provider = FakeProvider([[StreamEvent(text="恢复后回答"), StreamEvent(done=True)]])
    recorder = RecordingHookExecutor()
    hooks = HookEngine(
        [
            hook_rule("start", HookEvent.SESSION_START),
            hook_rule("end", HookEvent.SESSION_END),
            hook_rule("resume", HookEvent.SESSION_RESUME),
        ],
        [],
        recorder,  # type: ignore[arg-type]
    )
    monkeypatch.setattr("Licode.tui.app.new_provider", lambda config: provider)
    app = LiCodeApp(
        [provider_config()],
        "test",
        new_default_registry(),
        permission_engine(tmp_path),
        runtime,
        current_writer,
        sessions_dir=str(sessions_dir),
        hook_engine=hooks,
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.submit("/resume")
        assert app.state is SessionState.RESUMING
        assert app.query_one("#resume-select", OptionList).option_count == 2
        await pilot.press("a", "l", "p", "h", "a")
        assert app.query_one("#resume-select", OptionList).option_count == 1
        assert app.resume_query == "alpha"
        await pilot.press("escape")
        assert app.state is SessionState.IDLE
        assert app.runtime.session.session_id != history_dir.name

        await app.submit("/resume")
        await pilot.press("a", "l", "p", "h", "a")
        await pilot.press("enter")
        await wait_for_state(pilot, app, SessionState.IDLE)
        assert app.runtime.session.session_id == history_dir.name
        assert app.conv.messages()[0].content == "alpha 历史问题"
        assert "本会话已暂停" in app.conv.messages()[-1].content
        assert "已恢复会话" in app._transcript[-1].plain

        before = len(history_path.read_text(encoding="utf-8").splitlines())
        await app.submit("继续")
        await wait_for_state(pilot, app, SessionState.IDLE)
        after = len(history_path.read_text(encoding="utf-8").splitlines())
        assert after >= before + 2
        assert app.conv.messages()[-1].content == "恢复后回答"

    assert recorder.calls[:3] == [
        ("start", HookEvent.SESSION_START),
        ("end", HookEvent.SESSION_END),
        ("resume", HookEvent.SESSION_RESUME),
    ]

    assert app.writer is not None
    app.writer.close()


@pytest.mark.asyncio
async def test_resume_while_streaming_returns_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = FakeProvider([[StreamEvent(text="完成"), StreamEvent(done=True)]])
    app = make_app(tmp_path, monkeypatch, provider)

    async with app.run_test() as pilot:
        await pilot.pause()
        app.state = SessionState.STREAMING
        await app.submit("/resume")
        assert "请等待当前任务完成" in app._transcript[-1].plain
        assert app.state is SessionState.STREAMING


@pytest.mark.asyncio
async def test_resume_over_token_limit_compacts_before_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sessions_dir = tmp_path / ".Licode" / "sessions"
    history_dir = sessions_dir / "20260817-130000-babe"
    history_dir.mkdir(parents=True)
    history_path = history_dir / "conversation.jsonl"
    entries = []
    for index in range(12):
        entries.extend(
            (
                {
                    "role": "user",
                    "content": f"beta {index} " + "u" * 2000,
                    "model": "fake-model" if index == 0 else None,
                    "ts": int(time.time()),
                },
                {
                    "role": "assistant",
                    "content": "a" * 2000,
                    "ts": int(time.time()),
                },
            )
        )
    history_path.write_text(
        "\n".join(json.dumps(entry, ensure_ascii=False) for entry in entries) + "\n",
        encoding="utf-8",
    )
    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(str(tmp_path)),
        context_window=34000,
    )
    current_writer = Writer(runtime.session.session_dir)
    summary = "<analysis>草稿</analysis><summary>恢复摘要</summary>"
    provider = FakeProvider([[StreamEvent(text=summary), StreamEvent(done=True)]])
    monkeypatch.setattr("Licode.tui.app.new_provider", lambda config: provider)
    config = provider_config()
    config.context_window = 34000
    app = LiCodeApp(
        [config],
        "test",
        new_default_registry(),
        permission_engine(tmp_path),
        runtime,
        current_writer,
        sessions_dir=str(sessions_dir),
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        await app.submit("/resume")
        await pilot.press("b", "e", "t", "a")
        await pilot.press("enter")
        await wait_for_state(pilot, app, SessionState.IDLE)

        assert provider.call_count == 1
        assert app.conv.length() < len(entries)
        records = [
            json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines()
        ]
        assert any(record.get("type") == "compact" for record in records)

    assert app.writer is not None
    app.writer.close()
