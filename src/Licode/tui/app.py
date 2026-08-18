"""LiCode 的 Textual 应用与会话状态机。"""

import asyncio
import os
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from rich.console import Console, RenderableType
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message as TextualMessage
from textual.timer import Timer
from textual.widgets import OptionList, RichLog, Static, TextArea

from Licode.agent import Agent, ApprovalRequest, SessionRuntime, new_agent
from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from Licode.config import ProviderConfig, effective_context_window
from Licode.conversation import Conversation
from Licode.llm import Provider, new_provider
from Licode.permission import Engine, Mode, Outcome
from Licode.prompt import render_banner
from Licode.tool import Registry, new_default_registry

from .commands import dispatch_command
from .select import provider_at, provider_options
from .stream import consume_stream, tick
from .view import (
    approval_block,
    assistant_block,
    error_block,
    notice_block,
    status_bar,
    streaming_block,
    user_block,
)


class SessionState(Enum):
    SELECTING = "selecting"
    IDLE = "idle"
    STREAMING = "streaming"
    APPROVING = "approving"


@dataclass
class ToolDisplay:
    name: str
    args: str


class MessageInput(TextArea):
    """Enter 提交、Alt+Enter 换行的多行输入框。"""

    class Submitted(TextualMessage):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    BINDINGS = [
        Binding("enter", "submit_message", "Submit", show=False, priority=True),
        Binding("alt+enter", "insert_newline", "New line", show=False, priority=True),
    ]

    def action_submit_message(self) -> None:
        self.post_message(self.Submitted(self.text))

    def action_insert_newline(self) -> None:
        self.insert("\n")


class LiCodeApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }
    #log {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
    }
    #streaming {
        width: 1fr;
        height: auto;
        max-height: 40%;
        padding: 0 1;
    }
    #input-hint {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #input {
        width: 1fr;
        height: 5;
        border-top: solid $primary;
        padding: 0 1;
    }
    #statusbar {
        width: 1fr;
        height: 1;
        padding: 0 1;
        background: $panel;
    }
    #provider-select {
        display: none;
        width: 1fr;
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("escape", "cancel_turn", "Cancel", priority=True),
        Binding("shift+tab", "cycle_mode", "Mode", priority=True),
    ]

    def __init__(
        self,
        providers: list[ProviderConfig],
        version: str,
        registry: Registry,
        engine: Engine,
        runtime: SessionRuntime | None = None,
    ) -> None:
        super().__init__()
        self.state = SessionState.SELECTING if len(providers) > 1 else SessionState.IDLE
        self.providers = providers
        self.version = version
        self.provider: Provider | None = None
        self._tool_registry = registry
        self.engine = engine
        self.runtime = runtime or SessionRuntime(
            replacement=ContentReplacementState(),
            recovery=RecoveryState(),
            auto_tracking=CompactCircuitBreaker(),
            session=new_session_context(str(Path.cwd())),
        )
        self.agent: Agent | None = None
        self.conv = Conversation()
        self.mode = engine.start_mode()
        self.iter = 0
        self.usage_in = 0
        self.usage_out = 0
        self.cur_reply = ""
        self.cur_tools: list[ToolDisplay] = []
        self.turn_cancel: asyncio.Event | None = None
        self.turn_start = 0.0
        self.pending: ApprovalRequest | None = None
        self.approve_cursor = 0
        self._stream_task: asyncio.Task[None] | None = None
        self._timer: Timer | None = None
        self._transcript: list[RenderableType] = []

    def compose(self) -> ComposeResult:
        yield OptionList(*provider_options(self.providers), id="provider-select")
        yield RichLog(id="log", wrap=True, markup=True)
        yield Static(id="streaming")
        yield Static("❯ Send a message...", id="input-hint")
        yield MessageInput(id="input", show_line_numbers=False)
        yield Static(id="statusbar")

    def on_mount(self) -> None:
        banner = render_banner(self.version, os.getcwd())
        self.query_one("#log", RichLog).write(banner)
        self._transcript.append(banner)
        if len(self.providers) == 1:
            self._activate_provider(self.providers[0])
        else:
            self._show_provider_selection()

    def _show_provider_selection(self) -> None:
        self.state = SessionState.SELECTING
        self.query_one("#provider-select", OptionList).styles.display = "block"
        for selector in ("#log", "#streaming", "#input-hint", "#input", "#statusbar"):
            self.query_one(selector).styles.display = "none"
        self.query_one("#provider-select", OptionList).focus()

    def _activate_provider(self, cfg: ProviderConfig) -> None:
        self.provider = new_provider(cfg)
        self.runtime.context_window = effective_context_window(cfg)
        self.agent = new_agent(
            self.provider,
            self._tool_registry,
            self.version,
            self.engine,
            runtime=self.runtime,
        )
        self.state = SessionState.IDLE
        self.query_one("#provider-select", OptionList).styles.display = "none"
        for selector in ("#log", "#streaming", "#input-hint", "#input", "#statusbar"):
            self.query_one(selector).styles.display = "block"
        self._update_status_bar()
        self.query_one("#input", MessageInput).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._activate_provider(provider_at(self.providers, event.option.id))

    async def on_message_input_submitted(self, event: MessageInput.Submitted) -> None:
        await self.submit(event.text)

    async def submit(self, text: str) -> None:
        if self.state is not SessionState.IDLE or not text.strip():
            return
        command = text.strip()
        handler, handled = dispatch_command(command)
        if handled and handler is not None:
            self.query_one("#input", MessageInput).text = ""
            await handler(self)
            return
        await self._start_turn(text, text)

    async def _start_turn(self, history_text: str, rendered_text: str) -> None:
        self.conv.add_user(history_text)
        rendered_user = user_block(rendered_text)
        self.query_one("#log", RichLog).write(rendered_user)
        self._transcript.append(rendered_user)
        self.query_one("#input", MessageInput).text = ""
        self.cur_reply = ""
        self.cur_tools = []
        self.iter = 0
        self.turn_cancel = asyncio.Event()
        self.turn_start = time.monotonic()
        self.state = SessionState.STREAMING
        self._refresh_streaming_view()
        self._timer = self.set_interval(0.1, self._tick)
        self._stream_task = asyncio.create_task(self._consume_agent_events())

    def _write_notice(self, text: str) -> None:
        rendered_notice = notice_block(text)
        self.query_one("#log", RichLog).write(rendered_notice)
        self._transcript.append(rendered_notice)

    async def _consume_agent_events(self) -> None:
        await consume_stream(self)

    def _tick(self) -> None:
        tick(self)

    def _refresh_streaming_view(self) -> None:
        if self.state is SessionState.APPROVING and self.pending is not None:
            self.query_one("#streaming", Static).update(
                approval_block(self.pending, self.approve_cursor)
            )
            return
        if self.state is not SessionState.STREAMING:
            return
        elapsed = time.monotonic() - self.turn_start
        self.query_one("#streaming", Static).update(
            streaming_block(
                self.cur_reply,
                elapsed,
                self.iter,
                [(tool.name, tool.args) for tool in self.cur_tools],
            )
        )

    def _finish_turn(self) -> float:
        elapsed = time.monotonic() - self.turn_start
        if self._timer is not None:
            self._timer.stop()
        self._timer = None
        self._stream_task = None
        self.cur_tools = []
        self.iter = 0
        self.turn_cancel = None
        self.pending = None
        message_input = self.query_one("#input", MessageInput)
        message_input.disabled = False
        self.state = SessionState.IDLE
        self.query_one("#streaming", Static).update("")
        message_input.focus()
        return elapsed

    def _finish_with_assistant(self, reply: str) -> None:
        elapsed = self._finish_turn()
        rendered_reply = assistant_block(reply, elapsed)
        self.query_one("#log", RichLog).write(rendered_reply)
        self._transcript.append(rendered_reply)
        self.cur_reply = ""

    def _finish_with_error(self, error: Exception) -> None:
        self._finish_turn()
        rendered_error = error_block(error)
        self.query_one("#log", RichLog).write(rendered_error)
        self._transcript.append(rendered_error)
        self.cur_reply = ""

    def _update_status_bar(self) -> None:
        if self.provider is None:
            return
        self.query_one("#statusbar", Static).update(
            status_bar(
                self.mode,
                self.provider.model,
                self.usage_in,
                self.usage_out,
            )
        )

    def print_transcript(self) -> None:
        """退出 TUI 后把完成内容写回普通终端滚动历史。"""

        console = Console()
        for renderable in self._transcript:
            console.print(renderable)

    async def action_quit(self) -> None:
        if self.state in {SessionState.STREAMING, SessionState.APPROVING}:
            self._deny_pending()
        if self.state in {SessionState.STREAMING, SessionState.APPROVING} and self.turn_cancel:
            self.turn_cancel.set()
            return
        if self._stream_task is not None:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
        self.exit()

    def action_cancel_turn(self) -> None:
        if self.state in {SessionState.STREAMING, SessionState.APPROVING}:
            self._deny_pending()
        if self.state in {SessionState.STREAMING, SessionState.APPROVING} and self.turn_cancel:
            self.turn_cancel.set()

    def action_cycle_mode(self) -> None:
        if self.state is not SessionState.IDLE:
            return
        self.mode = next_mode(self.mode)
        rendered = notice_block(f"已切换到 {self.mode} 模式")
        self.query_one("#log", RichLog).write(rendered)
        self._transcript.append(rendered)
        self._update_status_bar()

    def on_key(self, event: events.Key) -> None:
        if self.state is not SessionState.APPROVING:
            return
        key = event.key
        if key in {"up", "k"}:
            self.approve_cursor = (self.approve_cursor - 1) % 3
        elif key in {"down", "j"}:
            self.approve_cursor = (self.approve_cursor + 1) % 3
        elif key in {"enter", "space"}:
            self._resolve_approval(outcome_for_index(self.approve_cursor))
        elif key in {"1", "2", "3"}:
            self._resolve_approval(outcome_for_index(int(key) - 1))
        elif key == "y":
            self._resolve_approval(Outcome.ALLOW_ONCE)
        elif key in {"n", "d"}:
            self._resolve_approval(Outcome.DENY_ONCE)
        else:
            return
        event.prevent_default()
        event.stop()
        self._refresh_streaming_view()

    def _show_approval(self, request: ApprovalRequest) -> None:
        self.pending = request
        self.approve_cursor = 0
        self.state = SessionState.APPROVING
        self.query_one("#input", MessageInput).disabled = True
        self.set_focus(None)
        self._refresh_streaming_view()

    def _resolve_approval(self, outcome: Outcome) -> None:
        request = self.pending
        self.pending = None
        self.state = SessionState.STREAMING
        self.query_one("#input", MessageInput).disabled = False
        if request is not None and not request.respond.done():
            request.respond.set_result(outcome)

    def _deny_pending(self) -> None:
        if self.pending is not None:
            self._resolve_approval(Outcome.DENY_ONCE)


def next_mode(mode: Mode) -> Mode:
    return Mode((int(mode) + 1) % len(Mode))


def outcome_for_index(index: int) -> Outcome:
    return (Outcome.ALLOW_ONCE, Outcome.ALLOW_FOREVER, Outcome.DENY_ONCE)[index]


def run(providers: list[ProviderConfig]) -> None:
    from Licode import __version__
    from Licode.permission import new_engine

    engine, _ = new_engine(str(Path.cwd().resolve()))
    app = LiCodeApp(providers, __version__, new_default_registry(), engine)
    app.run(inline=True, inline_no_clear=True)
    app.print_transcript()
