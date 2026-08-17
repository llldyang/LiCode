"""流式事件消费与计时辅助逻辑。"""

import asyncio
from typing import TYPE_CHECKING

from rich.markdown import Markdown
from textual.widgets import RichLog

from Licode.agent import Agent, Phase

from .view import tool_line, tool_result_summary

if TYPE_CHECKING:
    from .app import LiCodeApp


async def consume_stream(app: "LiCodeApp") -> None:
    try:
        if app.provider is None:
            raise RuntimeError("尚未选择 provider")
        agent = Agent(app.provider, app._tool_registry)
        async for event in agent.run(app.conv):
            if event.err is not None:
                app._finish_with_error(event.err)
                return
            if event.text:
                app.cur_reply += event.text
                app._refresh_streaming_view()
            if event.tool is not None and event.tool.phase is Phase.START:
                from .app import ToolDisplay

                if app.cur_reply:
                    rendered = Markdown(app.cur_reply)
                    app.query_one("#log", RichLog).write(rendered)
                    app._transcript.append(rendered)
                    app.cur_reply = ""
                app._cur_tool = ToolDisplay(event.tool.name, event.tool.args)
                app._refresh_streaming_view()
            if event.tool is not None and event.tool.phase is Phase.END:
                rendered_line = tool_line(event.tool.name, event.tool.args)
                rendered_result = tool_result_summary(event.tool.result, event.tool.is_error)
                app.query_one("#log", RichLog).write(rendered_line)
                app.query_one("#log", RichLog).write(rendered_result)
                app._transcript.extend((rendered_line, rendered_result))
                app._cur_tool = None
                app._refresh_streaming_view()
            if event.done:
                app._finish_with_assistant(app.cur_reply)
                return
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        app._finish_with_error(exc)


def tick(app: "LiCodeApp") -> None:
    app._refresh_streaming_view()
