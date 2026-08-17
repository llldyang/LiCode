from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from Licode.llm import Message, Request, System
from Licode.llm.anthropic_provider import AnthropicProvider


class FakeStream:
    async def __aenter__(self) -> "FakeStream":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def __aiter__(self) -> AsyncIterator[object]:
        return self._events()

    async def _events(self) -> AsyncIterator[object]:
        if False:
            yield object()

    async def get_final_message(self) -> SimpleNamespace:
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[],
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=2,
                cache_creation_input_tokens=8,
                cache_read_input_tokens=4,
            ),
        )


class FakeMessages:
    def __init__(self) -> None:
        self.params: dict[str, Any] = {}

    def stream(self, **params: Any) -> FakeStream:
        self.params = params
        return FakeStream()


@pytest.mark.asyncio
async def test_anthropic_stable_system_has_cache_breakpoint_and_environment_does_not() -> None:
    messages = FakeMessages()
    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider._client = SimpleNamespace(messages=messages)
    provider._model = "fake-model"
    provider._thinking = False
    request = Request(
        messages=[Message(role="user", content="问题")],
        system=System(stable="稳定系统提示", environment="动态环境"),
        reminder="<system-reminder>提醒</system-reminder>",
    )

    events = [event async for event in provider.stream(request)]

    assert messages.params["system"] == [
        {
            "type": "text",
            "text": "稳定系统提示",
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": "动态环境"},
    ]
    wire_messages = messages.params["messages"]
    assert len(wire_messages) == 1
    assert wire_messages[0]["role"] == "user"
    assert wire_messages[0]["content"][-1]["text"] == request.reminder
    usage = next(event.usage for event in events if event.usage is not None)
    assert usage.cache_write == 8
    assert usage.cache_read == 4
