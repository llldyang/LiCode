"""历史会话选择、搜索与恢复流程。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from textual import events
from textual.widgets import Static
from textual.widgets.option_list import Option

from Licode.compact import open_session_context
from Licode.compact.const import AUTO_SAFETY_MARGIN, SUMMARY_RESERVE
from Licode.compact.token import estimate_tokens
from Licode.conversation import Conversation
from Licode.permission import Mode
from Licode.session import SessionInfo, Writer, list_sessions, load_session, load_session_timestamp

if TYPE_CHECKING:
    from .app import LiCodeApp


@dataclass(frozen=True)
class SessionItem:
    info: SessionInfo

    @property
    def display_text(self) -> str:
        return (
            f"{self.info.title} · {_relative_time(self.info.modified_at)} · "
            f"{self.info.model or '(unknown model)'} · {_file_size(self.info.size)}"
        )


def begin_resume(app: LiCodeApp) -> None:
    """扫描会话并进入选择状态。"""

    sessions = list_sessions(app.sessions_dir)
    if not sessions:
        app._write_notice("没有可恢复的会话")
        return
    app.resume_sessions = sessions
    app.resume_query = ""
    app._refresh_resume_options()
    app._show_resume_selection()


def handle_resume_key(app: LiCodeApp, event: events.Key) -> None:
    """处理搜索输入；方向键和 Enter 由 OptionList 处理。"""

    if event.key == "backspace":
        app.resume_query = app.resume_query[:-1]
    elif (
        event.character
        and event.character.isprintable()
        and not event.key.startswith(("ctrl+", "alt+"))
    ):
        app.resume_query += event.character
    else:
        return
    app._refresh_resume_options()
    event.prevent_default()
    event.stop()


async def do_resume_session(app: LiCodeApp, info: SessionInfo) -> None:
    """恢复所选会话，并把后续消息继续写入原 JSONL。"""

    if app.agent is None or app.provider is None:
        app._cancel_resume()
        app._write_notice("恢复失败：尚未选择 provider")
        return
    app.query_one("#resume-search", Static).update("正在加载会话...")
    messages = load_session(info.dir)
    last_timestamp = load_session_timestamp(info.dir)
    new_writer: Writer | None = None
    old_session = app.runtime.session
    try:
        new_context = open_session_context(app.workspace, info.id)
        new_writer = Writer.open_existing(info.dir)
        new_writer.set_model(app.provider.model)
        conversation = Conversation.from_messages(
            messages,
            new_writer.on_append,
            new_writer.on_replace,
        )
        app.runtime.session = new_context
        threshold = app.runtime.context_window - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN
        if estimate_tokens(0, messages, 0) > threshold:
            definitions = (
                app._tool_registry.read_only_definitions()
                if app.mode() is Mode.PLAN
                else app._tool_registry.definitions()
            )
            try:
                await app.agent.run_force_compact(conversation, definitions)
            except Exception as exc:
                app._write_notice(f"恢复会话时压缩失败，继续加载原历史：{exc}")
        if last_timestamp and time.time() - last_timestamp > 6 * 60 * 60:
            duration = _duration_text(int(time.time() - last_timestamp))
            conversation.add_user(
                f"[系统提示] 本会话已暂停 {duration}。"
                "部分上下文可能已过时，如需最新信息请重新读取相关文件。"
            )
    except Exception as exc:
        app.runtime.session = old_session
        if new_writer is not None:
            new_writer.close()
        app._cancel_resume()
        app._write_notice(f"恢复会话失败：{exc}")
        return

    old_writer = app.writer
    app.writer = new_writer
    app.conv = conversation
    app.runtime.usage_anchor = 0
    app.runtime.anchor_msg_len = 0
    if old_writer is not None:
        old_writer.close()
    app._cancel_resume()
    app._write_notice(f"已恢复会话 {info.id}，共 {conversation.length()} 条消息")


def options_for(sessions: list[SessionInfo], query: str) -> list[Option]:
    normalized = query.casefold()
    return [
        Option(SessionItem(info).display_text, id=info.id)
        for info in sessions
        if normalized in info.title.casefold()
    ]


def _relative_time(value: datetime) -> str:
    seconds = max(0, int((datetime.now() - value).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} minutes ago"
    if seconds < 86400:
        return f"{seconds // 3600} hours ago"
    return f"{seconds // 86400} days ago"


def _file_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size / 1024 / 1024:.1f}MB"


def _duration_text(seconds: int) -> str:
    if seconds < 86400:
        return f"{seconds // 3600} 小时"
    return f"{seconds // 86400} 天"
