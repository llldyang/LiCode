"""斜杠命令与 Textual App 之间的薄分发层。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from Licode.command import Kind, parse_with_args

if TYPE_CHECKING:
    from .app import LiCodeApp


async def dispatch_slash(app: LiCodeApp, text: str) -> bool:
    """分发斜杠命令，返回输入是否已按命令处理。"""

    name, args, is_slash = parse_with_args(text)
    if not is_slash:
        return False

    app._pending_println.clear()
    command = app.cmd_registry.lookup(name)
    if command is None:
        app.println("未知命令。输入 /help 查看可用命令")
    elif command.kind in {Kind.UI, Kind.PROMPT} and not app.idle():
        app.error("请等待当前任务完成")
    else:
        try:
            if args and command.args_handler is None:
                app.error("该命令不接受参数")
            elif command.args_handler is not None:
                await command.args_handler(app, args)
            else:
                await command.handler(app)
            if command.kind is Kind.PROMPT:
                await asyncio.sleep(0)
            if app._pending_command_task is not None:
                task = app._pending_command_task
                app._pending_command_task = None
                await task
        except Exception as exc:
            app.error(str(exc))
    app._flush_command_output()
    return True
