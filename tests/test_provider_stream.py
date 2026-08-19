from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import anthropic
import openai
import pytest

from Licode.config import ProviderConfig
from Licode.llm import Message, Request, System
from Licode.llm.anthropic_provider import AnthropicProvider
from Licode.llm.openai_provider import OpenAIProvider


class OpenAIStream:
    def __init__(self, chunks: list[object]) -> None:
        self.chunks = chunks

    def __aiter__(self) -> AsyncIterator[object]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[object]:
        for chunk in self.chunks:
            yield chunk


class OpenAICompletions:
    def __init__(self, chunks: list[object]) -> None:
        self.chunks = chunks
        self.params: dict[str, Any] = {}

    async def create(self, **params: Any) -> OpenAIStream:
        self.params = params
        return OpenAIStream(self.chunks)


class AnthropicStream:
    def __init__(self, events: list[object], final_message: object) -> None:
        self.events = events
        self.final_message = final_message

    async def __aenter__(self) -> "AnthropicStream":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    def __aiter__(self) -> AsyncIterator[object]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[object]:
        for event in self.events:
            yield event

    async def get_final_message(self) -> object:
        return self.final_message


class AnthropicMessages:
    def __init__(self, stream: AnthropicStream) -> None:
        self.fake_stream = stream
        self.params: dict[str, Any] = {}

    def stream(self, **params: Any) -> AnthropicStream:
        self.params = params
        return self.fake_stream


def openai_chunk(text: str = "", *, finish_reason: str | None = None) -> object:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                delta=SimpleNamespace(content=text, tool_calls=[]),
            )
        ],
        usage=None,
    )


@pytest.mark.asyncio
async def test_openai_streams_text_usage_and_uses_custom_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = SimpleNamespace(
        prompt_tokens=12,
        completion_tokens=3,
        prompt_tokens_details=SimpleNamespace(cached_tokens=4),
    )
    chunks = [
        openai_chunk("你"),
        openai_chunk("好", finish_reason="stop"),
        SimpleNamespace(choices=[], usage=usage),
    ]
    completions = OpenAICompletions(chunks)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    constructor: dict[str, Any] = {}

    def fake_client(**params: Any) -> object:
        constructor.update(params)
        return client

    monkeypatch.setattr(openai, "AsyncOpenAI", fake_client)
    provider = OpenAIProvider(
        ProviderConfig(
            "兼容服务",
            "openai",
            "test-key",
            "test-model",
            base_url="https://example.invalid/v1",
        )
    )
    request = Request(
        messages=[Message(role="user", content="问题")],
        system=System(stable="系统规则"),
    )

    events = [event async for event in provider.stream(request)]

    assert constructor == {
        "api_key": "test-key",
        "base_url": "https://example.invalid/v1",
    }
    assert [event.text for event in events if event.text] == ["你", "好"]
    stream_usage = next(event.usage for event in events if event.usage is not None)
    assert (stream_usage.input_tokens, stream_usage.output_tokens, stream_usage.cache_read) == (
        12,
        3,
        4,
    )
    assert completions.params["messages"] == [
        {"role": "system", "content": "系统规则"},
        {"role": "user", "content": "问题"},
    ]
    assert completions.params["stream"] is True
    assert events[-1].done


@pytest.mark.asyncio
async def test_anthropic_enables_thinking_but_discards_thinking_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = AnthropicStream(
        [
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="thinking_delta", thinking="不可展示的思考"),
            ),
            SimpleNamespace(
                type="content_block_delta",
                delta=SimpleNamespace(type="text_delta", text="最终回复"),
            ),
        ],
        SimpleNamespace(
            stop_reason="end_turn",
            content=[],
            usage=SimpleNamespace(
                input_tokens=8,
                output_tokens=2,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            ),
        ),
    )
    messages = AnthropicMessages(stream)
    client = SimpleNamespace(messages=messages)
    constructor: dict[str, Any] = {}

    def fake_client(**params: Any) -> object:
        constructor.update(params)
        return client

    monkeypatch.setattr(anthropic, "AsyncAnthropic", fake_client)
    provider = AnthropicProvider(
        ProviderConfig(
            "Claude",
            "anthropic",
            "test-key",
            "claude-test",
            base_url="https://example.invalid/anthropic",
            thinking=True,
        )
    )

    events = [
        event
        async for event in provider.stream(
            Request(
                messages=[Message(role="user", content="问题")],
                system=System(stable="系统规则"),
            )
        )
    ]

    assert constructor == {
        "api_key": "test-key",
        "base_url": "https://example.invalid/anthropic",
    }
    assert messages.params["thinking"] == {"type": "enabled", "budget_tokens": 2048}
    assert [event.text for event in events if event.text] == ["最终回复"]
    assert all("不可展示" not in event.text for event in events)
    assert events[-1].done
