"""在并发工具执行中标记当前 Agent 与会话。"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Licode.conversation import Conversation

    from . import Agent

_current_agent: ContextVar[Agent | None] = ContextVar("Licode_current_agent", default=None)
_current_conversation: ContextVar[Conversation | None] = ContextVar(
    "Licode_current_conversation", default=None
)


def set_execution_context(
    agent: Agent, conversation: Conversation | None
) -> tuple[Token[Agent | None], Token[Conversation | None]]:
    return _current_agent.set(agent), _current_conversation.set(conversation)


def reset_execution_context(
    tokens: tuple[Token[Agent | None], Token[Conversation | None]],
) -> None:
    _current_agent.reset(tokens[0])
    _current_conversation.reset(tokens[1])


def current_agent() -> Agent | None:
    return _current_agent.get()


def current_conversation() -> Conversation | None:
    return _current_conversation.get()
