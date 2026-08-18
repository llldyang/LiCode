"""TUI 内置斜杠命令的统一分发。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from Licode.agent import CompactEvent, CompactPhase
from Licode.permission import Mode
from Licode.prompt import EXECUTE_DIRECTIVE

if TYPE_CHECKING:
    from .app import LiCodeApp

CommandHandler = Callable[["LiCodeApp"], Awaitable[None]]


def format_compact_notice(event: CompactEvent) -> str:
    if event.phase is CompactPhase.BEFORE_AUTO:
        return "正在压缩上下文..."
    if event.phase is CompactPhase.BEFORE_EMERGENCY:
        return "上下文撞墙，自动压缩中..."
    if event.err is not None:
        return f"压缩失败：{event.err}"
    return f"已压缩，token 从 {event.before} 降至 {event.after}"


async def handle_exit(app: LiCodeApp) -> None:
    await app.action_quit()


async def handle_plan(app: LiCodeApp) -> None:
    app.mode = Mode.PLAN
    app._write_notice("已进入计划模式（只读工具）")
    app._update_status_bar()


async def handle_do(app: LiCodeApp) -> None:
    app.mode = Mode.DEFAULT
    app._update_status_bar()
    await app._start_turn(EXECUTE_DIRECTIVE, "/do")


async def handle_compact(app: LiCodeApp) -> None:
    if app.agent is None:
        app._write_notice("压缩失败：尚未选择 provider")
        return
    if app.mode is Mode.PLAN:
        definitions = app._tool_registry.read_only_definitions()
    else:
        definitions = app._tool_registry.definitions()
    try:
        before, after = await app.agent.run_force_compact(app.conv, definitions)
    except Exception as exc:
        event = CompactEvent(phase=CompactPhase.AFTER_AUTO, err=exc)
    else:
        event = CompactEvent(
            phase=CompactPhase.AFTER_AUTO,
            before=before,
            after=after,
        )
    app._write_notice(format_compact_notice(event))


BUILTIN_COMMANDS: dict[str, CommandHandler] = {
    "/exit": handle_exit,
    "/plan": handle_plan,
    "/do": handle_do,
    "/compact": handle_compact,
}


def _unknown_handler(command: str) -> CommandHandler:
    async def unknown(app: LiCodeApp) -> None:
        available = " ".join(BUILTIN_COMMANDS)
        app._write_notice(f"未知命令: {command}，可用命令: {available}")

    return unknown


def dispatch_command(input_: str) -> tuple[CommandHandler | None, bool]:
    command = input_.strip()
    if not command.startswith("/"):
        return None, False
    return BUILTIN_COMMANDS.get(command, _unknown_handler(command)), True
