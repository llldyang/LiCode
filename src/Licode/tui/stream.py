"""流式事件消费与计时辅助逻辑。"""

import asyncio
from typing import TYPE_CHECKING

from rich.markdown import Markdown
from textual.widgets import RichLog

from Licode.agent import ApprovalRequest, Phase

from .view import error_block, format_compact_notice, notice_block, tool_line, tool_result_summary

if TYPE_CHECKING:
    from .app import LiCodeApp


async def consume_stream(app: "LiCodeApp") -> None:
    try:
        if app.provider is None:
            raise RuntimeError("尚未选择 provider")
        if app.turn_cancel is None:
            raise RuntimeError("本轮取消事件尚未初始化")
        if app.agent is None:
            raise RuntimeError("Agent 尚未初始化")
        async for event in app.run_agent_events():
            if isinstance(event, ApprovalRequest):
                app._show_approval(event)
                continue
            if event.compact is not None:
                app._write_notice(format_compact_notice(event.compact))
                continue
            if event.err is not None:
                rendered_error = error_block(event.err)
                app.query_one("#log", RichLog).write(rendered_error)
                app._transcript.append(rendered_error)
            if event.tool is not None and event.tool.phase is Phase.START:
                from .app import ToolDisplay

                if app.cur_reply:
                    rendered = Markdown(app.cur_reply)
                    app.query_one("#log", RichLog).write(rendered)
                    app._transcript.append(rendered)
                    app.cur_reply = ""
                app.cur_tools.append(ToolDisplay(event.tool.name, event.tool.args))
                app._refresh_streaming_view()
            if event.tool is not None and event.tool.phase is Phase.END:
                if app.cur_tools:
                    display = app.cur_tools.pop(0)
                    name, args = display.name, display.args
                else:
                    name, args = event.tool.name, event.tool.args
                rendered_line = tool_line(name, args)
                rendered_result = tool_result_summary(event.tool.result, event.tool.is_error)
                app.query_one("#log", RichLog).write(rendered_line)
                app.query_one("#log", RichLog).write(rendered_result)
                app._transcript.extend((rendered_line, rendered_result))
                app._refresh_streaming_view()
            if event.usage is not None:
                app._usage_in += event.usage.input
                app._usage_out += event.usage.output
                app._update_status_bar()
            if event.notice:
                rendered_notice = notice_block(event.notice)
                app.query_one("#log", RichLog).write(rendered_notice)
                app._transcript.append(rendered_notice)
            if event.iter > 0:
                app.iter = event.iter
                app._refresh_streaming_view()
            if event.done:
                if app.cur_reply:
                    app._finish_with_assistant(app.cur_reply)
                else:
                    app._finish_turn()
                # 继续拉取一次让上游生成器在当前任务内退出并完成 ContextVar 清理。
                continue
            if event.text:
                app.cur_reply += event.text
                app._refresh_streaming_view()
        from .app import SessionState

        if app.state is SessionState.STREAMING:
            app.cur_reply = ""
            app._finish_turn()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        app._finish_with_error(exc)


async def begin_autonomous_turn(app: "LiCodeApp") -> None:
    text = "[team-update] 队员发来新消息，请按 Coordinator 流程处理..."
    await app._start_turn(text, text)


def tick(app: "LiCodeApp") -> None:
    app._refresh_streaming_view()
