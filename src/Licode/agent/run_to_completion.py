"""SubAgent 的非交互运行入口。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from Licode.permission import Mode

from .event import Event

if TYPE_CHECKING:
    from Licode.conversation import Conversation

    from . import Agent, AgentOutput


class MaxTurnsReached(RuntimeError):
    """子 Agent 在限定轮数内未自然结束。"""

    def __init__(self, final_text: str) -> None:
        super().__init__("SubAgent reached max turns")
        self.final_text = final_text


async def run_to_completion(
    agent: Agent,
    conversation: Conversation,
    task: str,
    events: asyncio.Queue[AgentOutput | None] | None = None,
) -> str:
    """消费 Agent 事件并返回最后一条 assistant 文本。"""

    if task:
        conversation.add_user(task)
    reached_limit = False
    stream_error: Exception | None = None
    async for output in agent.run(
        conversation,
        agent.permission_mode or Mode.DEFAULT,
        asyncio.Event(),
    ):
        if events is not None:
            await events.put(output)
        if isinstance(output, Event):
            if output.notice and "最大迭代轮数" in output.notice:
                reached_limit = True
            if output.err is not None:
                stream_error = output.err
    messages = conversation.messages()
    final_text = next(
        (message.content for message in reversed(messages) if message.role == "assistant"),
        "",
    )
    if reached_limit:
        raise MaxTurnsReached(final_text)
    if stream_error is not None:
        raise stream_error
    return final_text
