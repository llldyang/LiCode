"""流式事件消费与计时辅助逻辑。"""

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import LiCodeApp


async def consume_stream(app: "LiCodeApp") -> None:
    try:
        if app.provider is None:
            raise RuntimeError("尚未选择 provider")
        async for event in app.provider.stream(app.conv.messages()):
            if event.err is not None:
                app._finish_with_error(event.err)
                return
            if event.text:
                app.cur_reply += event.text
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
