"""LiCode 的 Textual 应用与会话状态机。"""

import asyncio
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from rich.console import Console, RenderableType
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.message import Message as TextualMessage
from textual.timer import Timer
from textual.widgets import OptionList, RichLog, Static, TextArea

from Licode.agent import (
    Agent,
    AgentOutput,
    AgentTool,
    ApprovalRequest,
    CompactEvent,
    CompactPhase,
    SessionRuntime,
    new_agent,
)
from Licode.command import (
    Command,
    register_builtins,
    register_skills_as_commands,
    remove_skill_commands,
)
from Licode.command import Registry as CommandRegistry
from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from Licode.config import ProviderConfig, effective_context_window
from Licode.conversation import Conversation
from Licode.hook import DispatchResult
from Licode.hook import Engine as HookEngine
from Licode.hook import Event as HookEvent
from Licode.hook.rule import Payload
from Licode.hook.rule import Rule as HookRule
from Licode.llm import Provider, new_provider
from Licode.memory import Manager as MemoryManager
from Licode.permission import Engine, Mode, Outcome
from Licode.prompt import render_banner
from Licode.session import SessionInfo, Writer
from Licode.skills import Catalog, SkillSummary
from Licode.skills.executor import Executor
from Licode.subagent import Catalog as SubagentCatalog
from Licode.task import Manager as TaskManager
from Licode.tool import Registry as ToolRegistry
from Licode.tool import new_default_registry, with_cwd
from Licode.tool.install_skill import InstallSkillTool
from Licode.worktree import Manager as WorktreeManager

from .commands import dispatch_slash
from .complete import CompletionMenu, handle_completion_key
from .resume import begin_resume, do_resume_session, handle_resume_key, options_for
from .select import provider_at, provider_options
from .stream import consume_stream, tick
from .tasks import consume_subagent_approvals, consume_task_done
from .view import (
    approval_block,
    assistant_block,
    error_block,
    format_compact_notice,
    notice_block,
    status_bar,
    streaming_block,
    user_block,
)
from .worktree_adapter import WorktreeAdapter


class SessionState(Enum):
    SELECTING = "selecting"
    IDLE = "idle"
    STREAMING = "streaming"
    APPROVING = "approving"
    RESUMING = "resuming"


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
    #completion {
        display: none;
        width: 1fr;
        height: auto;
        max-height: 8;
        padding: 0 1;
        background: $panel;
    }
    #provider-select {
        display: none;
        width: 1fr;
        height: 1fr;
    }
    #resume-select {
        display: none;
        width: 1fr;
        height: 1fr;
    }
    #resume-search {
        display: none;
        width: 1fr;
        height: 1;
        padding: 0 1;
        color: $text-muted;
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
        registry: ToolRegistry,
        engine: Engine,
        runtime: SessionRuntime | None = None,
        writer: Writer | None = None,
        memory_manager: MemoryManager | None = None,
        instruction_text: str = "",
        memory_text: str = "",
        sessions_dir: str | None = None,
        catalog: Catalog | None = None,
        install_skill_tool: InstallSkillTool | None = None,
        hook_engine: HookEngine | None = None,
        task_mgr: TaskManager | None = None,
        subagent_catalog: SubagentCatalog | None = None,
        agent_tool: AgentTool | None = None,
        worktree_mgr: WorktreeManager | None = None,
    ) -> None:
        super().__init__()
        self.state = SessionState.SELECTING if len(providers) > 1 else SessionState.IDLE
        self.providers = providers
        self.version = version
        self.provider: Provider | None = None
        self._tool_registry = registry
        self.cmd_registry = CommandRegistry()
        register_builtins(self.cmd_registry)
        self.completion = CompletionMenu()
        self._pending_println: list[str] = []
        self._pending_command_task: asyncio.Task[None] | None = None
        self.engine = engine
        self.runtime = runtime or SessionRuntime(
            replacement=ContentReplacementState(),
            recovery=RecoveryState(),
            auto_tracking=CompactCircuitBreaker(),
            session=new_session_context(str(Path.cwd())),
        )
        self.hook_engine = hook_engine
        self.task_mgr = task_mgr or TaskManager()
        self.subagent_catalog = subagent_catalog or SubagentCatalog()
        self.agent_tool = agent_tool
        self.worktree_mgr = worktree_mgr
        current_worktree = worktree_mgr.current_session() if worktree_mgr is not None else None
        self.active_cwd = current_worktree.worktree_path if current_worktree is not None else ""
        self.foreground_sub_agent = None
        self._task_done_consumer: asyncio.Task[None] | None = None
        self._approval_consumer: asyncio.Task[None] | None = None
        self._approval_return_state = self.state
        self.runtime.hook_engine = hook_engine
        self._session_end_dispatched = False
        self.writer = writer
        self.memory_manager = memory_manager
        self.instruction_text = instruction_text
        self.memory_text = memory_text
        self.sessions_dir = sessions_dir or str(Path(self.runtime.session.session_dir).parent)
        self.workspace = str(Path(self.sessions_dir).resolve().parents[1])
        self.catalog = catalog or Catalog(Path(self.workspace))
        self.agent: Agent | None = None
        self.conv = Conversation(
            writer.on_append if writer is not None else None,
            writer.on_replace if writer is not None else None,
        )
        self.skill_executor = Executor(
            self.catalog,
            self.runtime.active_skills,
            self._tool_registry,
            self.engine,
            self.version,
            self.providers,
            instruction_text=self.instruction_text,
            memory_text=self.memory_text,
        )
        register_skills_as_commands(self.cmd_registry, self.catalog, self.skill_executor)
        self._install_skill_tool = install_skill_tool
        if self._install_skill_tool is not None:
            self._install_skill_tool.set_on_installed(self._reload_skill_commands)
        self._mode = engine.start_mode()
        self.iter = 0
        self._usage_in = 0
        self._usage_out = 0
        self.cur_reply = ""
        self.cur_tools: list[ToolDisplay] = []
        self.turn_cancel: asyncio.Event | None = None
        self.turn_start = 0.0
        self.pending: ApprovalRequest | None = None
        self.approve_cursor = 0
        self._stream_task: asyncio.Task[None] | None = None
        self._timer: Timer | None = None
        self._transcript: list[RenderableType] = []
        self.resume_sessions: list[SessionInfo] = []
        self.resume_query = ""

    def compose(self) -> ComposeResult:
        yield OptionList(*provider_options(self.providers), id="provider-select")
        yield OptionList(id="resume-select")
        yield Static(id="resume-search")
        yield RichLog(id="log", wrap=True, markup=True)
        yield Static(id="streaming")
        yield Static("❯ Send a message...", id="input-hint")
        yield MessageInput(id="input", show_line_numbers=False)
        yield Static(id="completion", markup=True)
        yield Static(id="statusbar")

    async def on_mount(self) -> None:
        banner = render_banner(self.version, os.getcwd())
        self.query_one("#log", RichLog).write(banner)
        self._transcript.append(banner)
        if len(self.providers) == 1:
            self._activate_provider(self.providers[0])
        else:
            self._show_provider_selection()
        self._task_done_consumer = asyncio.create_task(consume_task_done(self))
        self._approval_consumer = asyncio.create_task(consume_subagent_approvals(self))
        await self._dispatch_session_start()

    def _show_provider_selection(self) -> None:
        self.state = SessionState.SELECTING
        self.query_one("#provider-select", OptionList).styles.display = "block"
        for selector in (
            "#log",
            "#streaming",
            "#input-hint",
            "#input",
            "#completion",
            "#statusbar",
        ):
            self.query_one(selector).styles.display = "none"
        self.query_one("#provider-select", OptionList).focus()

    def _activate_provider(self, cfg: ProviderConfig) -> None:
        self.provider = new_provider(cfg)
        if self.writer is not None:
            self.writer.set_model(self.provider.model)
        if self.memory_manager is not None:
            self.memory_manager.set_provider(self.provider, self.provider.model)
        self.runtime.context_window = effective_context_window(cfg)
        self.agent = new_agent(
            self.provider,
            self._tool_registry,
            self.version,
            self.engine,
            runtime=self.runtime,
            memory_manager=self.memory_manager,
            instruction_text=self.instruction_text,
            memory_text=self.memory_text,
            hook_engine=self.hook_engine,
        ).with_catalog(self.catalog)
        if self.agent_tool is not None:
            self.agent_tool.set_parent(self.agent)
        self.skill_executor.bind(self.provider, self.conv)
        self.state = SessionState.IDLE
        self.query_one("#provider-select", OptionList).styles.display = "none"
        for selector in ("#log", "#streaming", "#input-hint", "#input", "#statusbar"):
            self.query_one(selector).styles.display = "block"
        self._render_completion()
        self._update_status_bar()
        self.query_one("#input", MessageInput).focus()

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.control.id == "resume-select":
            info = next(
                (item for item in self.resume_sessions if item.id == event.option.id),
                None,
            )
            if info is not None:
                await do_resume_session(self, info)
            return
        self._activate_provider(provider_at(self.providers, event.option.id))

    async def on_message_input_submitted(self, event: MessageInput.Submitted) -> None:
        if self.completion.active:
            selected = self.completion.selected()
            if selected is not None:
                await self._execute_selected(selected)
                return
        await self.submit(event.text)

    async def submit(self, text: str) -> None:
        command = text.strip()
        if not command:
            return
        if await self.dispatch_slash(command):
            self.input_area.text = ""
            self.completion.hide()
            self._render_completion()
            return
        if self.state is not SessionState.IDLE:
            return
        hook_result = await self._dispatch_hook(
            HookEvent.USER_PROMPT_SUBMIT,
            prompt=text,
        )
        if hook_result.blocked:
            self._write_error(f"[hook {hook_result.blocking_hook_name}] {hook_result.reason}")
            self.input_area.focus()
            return
        await self._start_turn(text, text)

    def _base_hook_payload(self, event: HookEvent) -> Payload:
        return {
            "event": event.value,
            "session_id": self.runtime.session.session_id,
            "cwd": self.workspace,
            "mode": str(self._mode),
        }

    async def _dispatch_hook(
        self,
        event: HookEvent,
        **fields: object,
    ) -> DispatchResult:
        if self.hook_engine is None:
            return DispatchResult()
        payload = self._base_hook_payload(event)
        payload.update(fields)
        result = await self.hook_engine.dispatch(event, payload)
        self.runtime.append_reminders(result.injected_prompts)
        return result

    async def _dispatch_session_start(self) -> None:
        self._session_end_dispatched = False
        await self._dispatch_hook(HookEvent.SESSION_START)

    async def dispatch_session_end(self) -> None:
        if self._session_end_dispatched:
            return
        await self._dispatch_hook(HookEvent.SESSION_END)
        self._session_end_dispatched = True

    async def _dispatch_session_resume(self) -> None:
        self._session_end_dispatched = False
        await self._dispatch_hook(HookEvent.SESSION_RESUME)

    async def _start_turn(self, history_text: str, rendered_text: str) -> None:
        self.conv.add_user(history_text)
        rendered_user = user_block(rendered_text)
        self.query_one("#log", RichLog).write(rendered_user)
        self._transcript.append(rendered_user)
        self.query_one("#input", MessageInput).text = ""
        # 一轮请求完成前不接收新输入，但仍允许滚动和取消等界面操作。
        self.query_one("#input", MessageInput).disabled = True
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

    def _write_error(self, text: str) -> None:
        rendered_error = error_block(RuntimeError(text))
        self.query_one("#log", RichLog).write(rendered_error)
        self._transcript.append(rendered_error)

    @property
    def input_area(self) -> MessageInput:
        return self.query_one("#input", MessageInput)

    async def dispatch_slash(self, text: str) -> bool:
        return await dispatch_slash(self, text)

    def println(self, msg: str) -> None:
        self._pending_println.append(msg)

    def error(self, msg: str) -> None:
        self._pending_println.append(f"ERROR\x00{msg}")

    def _flush_command_output(self) -> None:
        for message in self._pending_println:
            if message.startswith("ERROR\x00"):
                self._write_error(message.removeprefix("ERROR\x00"))
            else:
                self._write_notice(message)
        self._pending_println.clear()

    def mode(self) -> Mode:
        return self._mode

    def set_mode(self, mode: Mode) -> None:
        self._mode = mode
        self._update_status_bar()

    def inject_and_send(self, display_label: str, preset_prompt: str) -> None:
        asyncio.create_task(self._start_turn(preset_prompt, display_label))

    def usage_in(self) -> int:
        return self._usage_in

    def usage_out(self) -> int:
        return self._usage_out

    def model_name(self) -> str:
        return self.provider.model if self.provider is not None else ""

    def cwd(self) -> str:
        return self._effective_cwd()

    def tool_count(self) -> int:
        return self._tool_registry.count()

    def memory_files(self) -> list[str]:
        if self.memory_manager is None:
            return []
        project, user = self.memory_manager.list_files()
        return project + user

    def session_path(self) -> str:
        return self.writer.path if self.writer is not None else ""

    def session_id(self) -> str:
        return self.runtime.session.session_id if self.runtime is not None else ""

    def quit(self) -> None:
        asyncio.create_task(self.action_quit())

    def force_compact(self) -> None:
        self._pending_command_task = asyncio.create_task(self._run_force_compact())

    async def _run_force_compact(self) -> None:
        if self.agent is None:
            self._write_error("agent 未就绪")
            return
        definitions = (
            self._tool_registry.read_only_definitions()
            if self._mode is Mode.PLAN
            else self._tool_registry.definitions()
        )
        self._write_notice("正在压缩上下文...")
        try:
            before, after = await self.agent.run_force_compact(
                self.conv,
                definitions,
                self._mode,
            )
        except Exception as exc:
            event = CompactEvent(phase=CompactPhase.AFTER_AUTO, err=exc)
        else:
            event = CompactEvent(phase=CompactPhase.AFTER_AUTO, before=before, after=after)
        self._write_notice(format_compact_notice(event))

    def open_resume_menu(self) -> None:
        begin_resume(self)

    def clear_and_new_session(self) -> None:
        self._pending_command_task = asyncio.create_task(self._clear_and_new_session())

    async def _clear_and_new_session(self) -> None:
        await self.dispatch_session_end()
        if self.writer is not None:
            self.writer.close()
        session_context = new_session_context(self.workspace)
        new_writer = Writer(session_context.session_dir)
        if self.provider is not None:
            new_writer.set_model(self.provider.model)
        self.writer = new_writer
        self.conv = Conversation(new_writer.on_append, new_writer.on_replace)
        await self.runtime.reset_for_new_session(session_context)
        if self.provider is not None:
            self.skill_executor.bind(self.provider, self.conv)
        self.iter = 0
        self._usage_in = 0
        self._usage_out = 0
        self.cur_reply = ""
        self.cur_tools = []
        self._transcript.clear()
        self.query_one("#log", RichLog).clear()
        self._update_status_bar()
        await self._dispatch_session_start()

    def idle(self) -> bool:
        return self.state is SessionState.IDLE

    def list_catalog_skills(self) -> list[SkillSummary]:
        return self.catalog.summaries()

    def list_active_skills(self) -> list[str]:
        return self.runtime.active_skills.names()

    def clear_active_skills(self) -> None:
        self.runtime.active_skills.clear()

    def append_assistant_message(self, text: str) -> None:
        self.conv.add_assistant(text)
        rendered = assistant_block(text, 0.0)
        self.query_one("#log", RichLog).write(rendered)
        self._transcript.append(rendered)

    def hook_sources(self) -> list[str]:
        return self.hook_engine.sources if self.hook_engine is not None else []

    def hook_rules(self) -> list[HookRule]:
        return self.hook_engine.rules if self.hook_engine is not None else []

    def _set_active_cwd(self, path: str) -> None:
        self.active_cwd = path

    def _effective_cwd(self) -> str:
        return self.active_cwd or str(Path.cwd())

    def worktree_accessor(self) -> WorktreeAdapter | None:
        if self.worktree_mgr is None:
            return None
        return WorktreeAdapter(self.worktree_mgr, self._set_active_cwd)

    async def run_agent_events(self) -> AsyncIterator[AgentOutput]:
        if self.agent is None:
            raise RuntimeError("Agent 尚未初始化")
        if self.turn_cancel is None:
            raise RuntimeError("本轮取消事件尚未初始化")
        with with_cwd(self._effective_cwd()):
            async for event in self.agent.run(self.conv, self.mode(), self.turn_cancel):
                yield event

    def _reload_skill_commands(self) -> None:
        remove_skill_commands(self.cmd_registry)
        register_skills_as_commands(self.cmd_registry, self.catalog, self.skill_executor)
        self._sync_completion_from_input()

    async def _execute_selected(self, command: Command) -> None:
        self.input_area.text = "/" + command.name
        await self.submit(self.input_area.text)

    async def _handle_completion_key(self, event: events.Key) -> bool:
        return await handle_completion_key(self, event)

    def _sync_completion_from_input(self, input_text: str | None = None) -> None:
        value = self.input_area.text if input_text is None else input_text
        self.completion.update(value, self.cmd_registry)
        self._render_completion()

    def _render_completion(self) -> None:
        try:
            widget = self.query_one("#completion", Static)
        except NoMatches:
            return
        widget.styles.display = "block" if self.completion.active else "none"
        widget.update(self.completion.render(max(8, self.size.width - 2)))

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "input":
            self._sync_completion_from_input(event.text_area.text)

    def begin_resume(self) -> None:
        begin_resume(self)

    def _show_resume_selection(self) -> None:
        self.state = SessionState.RESUMING
        self.query_one("#resume-select", OptionList).styles.display = "block"
        self.query_one("#resume-search", Static).styles.display = "block"
        for selector in (
            "#provider-select",
            "#log",
            "#streaming",
            "#input-hint",
            "#input",
            "#completion",
            "#statusbar",
        ):
            self.query_one(selector).styles.display = "none"
        self.query_one("#resume-select", OptionList).focus()

    def _cancel_resume(self) -> None:
        self.state = SessionState.IDLE
        self.query_one("#resume-select", OptionList).styles.display = "none"
        self.query_one("#resume-search", Static).styles.display = "none"
        for selector in ("#log", "#streaming", "#input-hint", "#input", "#statusbar"):
            self.query_one(selector).styles.display = "block"
        self._render_completion()
        self.query_one("#input", MessageInput).focus()

    def _refresh_resume_options(self) -> None:
        option_list = self.query_one("#resume-select", OptionList)
        option_list.clear_options()
        option_list.add_options(options_for(self.resume_sessions, self.resume_query))
        option_list.highlighted = 0 if option_list.option_count else None
        self.query_one("#resume-search", Static).update(f"搜索: {self.resume_query}")

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
                self._mode,
                self.provider.model,
                self._usage_in,
                self._usage_out,
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
        await self.dispatch_session_end()
        for consumer in (self._task_done_consumer, self._approval_consumer):
            if consumer is not None:
                consumer.cancel()
        self.exit()

    @property
    def main_agent(self) -> Agent | None:
        return self.agent

    def action_cancel_turn(self) -> None:
        if self.state is SessionState.RESUMING:
            self._cancel_resume()
            return
        if self.state is SessionState.IDLE and self.completion.active:
            self.completion.hide()
            self._render_completion()
            self.input_area.focus()
            return
        if self.state in {SessionState.STREAMING, SessionState.APPROVING}:
            self._deny_pending()
        if self.state in {SessionState.STREAMING, SessionState.APPROVING} and self.turn_cancel:
            self.turn_cancel.set()

    def action_cycle_mode(self) -> None:
        if self.state is not SessionState.IDLE:
            return
        self._mode = next_mode(self._mode)
        rendered = notice_block(f"已切换到 {self._mode} 模式")
        self.query_one("#log", RichLog).write(rendered)
        self._transcript.append(rendered)
        self._update_status_bar()

    async def on_key(self, event: events.Key) -> None:
        if self.state is SessionState.RESUMING:
            handle_resume_key(self, event)
            return
        if self.state is SessionState.IDLE and await self._handle_completion_key(event):
            return
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
        self._approval_return_state = self.state
        self.pending = request
        self.approve_cursor = 0
        self.state = SessionState.APPROVING
        self.query_one("#input", MessageInput).disabled = True
        self.set_focus(None)
        self._refresh_streaming_view()

    def _resolve_approval(self, outcome: Outcome) -> None:
        request = self.pending
        self.pending = None
        self.state = self._approval_return_state
        # 审批结束通常仍处于模型流式阶段，输入框应由整轮结束逻辑统一恢复。
        self.query_one("#input", MessageInput).disabled = self.state is not SessionState.IDLE
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
