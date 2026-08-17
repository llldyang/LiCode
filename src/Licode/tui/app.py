"""LiCode 的 Textual 应用与会话状态机。"""

import asyncio
import os
import time
from enum import Enum

from rich.console import Console, RenderableType
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.message import Message as TextualMessage
from textual.timer import Timer
from textual.widgets import OptionList, RichLog, Static, TextArea

from Licode import __version__
from Licode.config import ProviderConfig
from Licode.conversation import Conversation
from Licode.llm import Provider, new_provider
from Licode.prompt import render_banner

from .select import provider_at, provider_options
from .stream import consume_stream, tick
from .view import assistant_block, error_block, status_bar, streaming_block, user_block


class SessionState(Enum):
    SELECTING = "selecting"
    IDLE = "idle"
    STREAMING = "streaming"


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

    BINDINGS = [Binding("ctrl+c", "quit", "Quit", priority=True)]

    def __init__(self, providers: list[ProviderConfig]) -> None:
        super().__init__()
        self.state = SessionState.SELECTING if len(providers) > 1 else SessionState.IDLE
        self.providers = providers
        self.provider: Provider | None = None
        self.conv = Conversation()
        self.cur_reply = ""
        self.turn_start = 0.0
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
        banner = render_banner(__version__, os.getcwd())
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
        self.state = SessionState.IDLE
        self.query_one("#provider-select", OptionList).styles.display = "none"
        for selector in ("#log", "#streaming", "#input-hint", "#input", "#statusbar"):
            self.query_one(selector).styles.display = "block"
        self.query_one("#statusbar", Static).update(
            status_bar(self.provider.name, self.provider.model)
        )
        self.query_one("#input", MessageInput).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._activate_provider(provider_at(self.providers, event.option.id))

    async def on_message_input_submitted(self, event: MessageInput.Submitted) -> None:
        await self.submit(event.text)

    async def submit(self, text: str) -> None:
        if self.state is not SessionState.IDLE or not text.strip():
            return
        if text.strip() == "/exit":
            await self.action_quit()
            return

        self.conv.add_user(text)
        rendered_user = user_block(text)
        self.query_one("#log", RichLog).write(rendered_user)
        self._transcript.append(rendered_user)
        self.query_one("#input", MessageInput).text = ""
        self.cur_reply = ""
        self.turn_start = time.monotonic()
        self.state = SessionState.STREAMING
        self._refresh_streaming_view()
        self._timer = self.set_interval(0.1, self._tick)
        self._stream_task = asyncio.create_task(self._consume_stream())

    async def _consume_stream(self) -> None:
        await consume_stream(self)

    def _tick(self) -> None:
        tick(self)

    def _refresh_streaming_view(self) -> None:
        if self.state is not SessionState.STREAMING:
            return
        elapsed = time.monotonic() - self.turn_start
        self.query_one("#streaming", Static).update(streaming_block(self.cur_reply, elapsed))

    def _finish_turn(self) -> float:
        elapsed = time.monotonic() - self.turn_start
        if self._timer is not None:
            self._timer.stop()
        self._timer = None
        self._stream_task = None
        self.state = SessionState.IDLE
        self.query_one("#streaming", Static).update("")
        return elapsed

    def _finish_with_assistant(self, reply: str) -> None:
        elapsed = self._finish_turn()
        rendered_reply = assistant_block(reply, elapsed)
        self.query_one("#log", RichLog).write(rendered_reply)
        self._transcript.append(rendered_reply)
        self.conv.add_assistant(reply)
        self.cur_reply = ""

    def _finish_with_error(self, error: Exception) -> None:
        self._finish_turn()
        rendered_error = error_block(error)
        self.query_one("#log", RichLog).write(rendered_error)
        self._transcript.append(rendered_error)
        self.cur_reply = ""

    def print_transcript(self) -> None:
        """退出 TUI 后把完成内容写回普通终端滚动历史。"""

        console = Console()
        for renderable in self._transcript:
            console.print(renderable)

    async def action_quit(self) -> None:
        if self._stream_task is not None:
            self._stream_task.cancel()
            try:
                await self._stream_task
            except asyncio.CancelledError:
                pass
        self.exit()


def run(providers: list[ProviderConfig]) -> None:
    app = LiCodeApp(providers)
    app.run(inline=True, inline_no_clear=True)
    app.print_transcript()
