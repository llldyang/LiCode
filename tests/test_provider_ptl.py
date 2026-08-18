from types import SimpleNamespace

import anthropic
import httpx
import openai
import pytest

from Licode.llm import Message, PromptTooLongError, Request
from Licode.llm.anthropic_provider import AnthropicProvider
from Licode.llm.openai_provider import OpenAIProvider


class AnthropicMessages:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def stream(self, **params):
        del params
        raise self.error


class OpenAICompletions:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def create(self, **params):
        del params
        raise self.error


def response() -> httpx.Response:
    request = httpx.Request("POST", "https://example.invalid")
    return httpx.Response(400, request=request)


def anthropic_error(message: str) -> anthropic.BadRequestError:
    return anthropic.BadRequestError(
        message,
        response=response(),
        body={"error": {"message": message}},
    )


def openai_error(code: str) -> openai.BadRequestError:
    return openai.BadRequestError(
        "bad request",
        response=response(),
        body={"error": {"code": code, "message": code}},
    )


@pytest.mark.asyncio
async def test_anthropic_wraps_prompt_too_long_and_keeps_other_errors() -> None:
    original = anthropic_error("prompt is too long")
    provider = AnthropicProvider.__new__(AnthropicProvider)
    provider._client = SimpleNamespace(messages=AnthropicMessages(original))
    provider._model = "fake"
    provider._thinking = False
    events = [
        event
        async for event in provider.stream(Request(messages=[Message(role="user", content="问题")]))
    ]
    assert isinstance(events[0].err, PromptTooLongError)
    assert events[0].err.__cause__ is original

    other = anthropic_error("invalid request")
    provider._client = SimpleNamespace(messages=AnthropicMessages(other))
    events = [event async for event in provider.stream(Request())]
    assert events[0].err is other


@pytest.mark.asyncio
async def test_openai_wraps_context_length_and_keeps_other_errors() -> None:
    original = openai_error("context_length_exceeded")
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider._client = SimpleNamespace(
        chat=SimpleNamespace(completions=OpenAICompletions(original))
    )
    provider._model = "fake"
    events = [event async for event in provider.stream(Request())]
    assert isinstance(events[0].err, PromptTooLongError)
    assert events[0].err.__cause__ is original

    other = openai_error("invalid_request")
    provider._client = SimpleNamespace(chat=SimpleNamespace(completions=OpenAICompletions(other)))
    events = [event async for event in provider.stream(Request())]
    assert events[0].err is other
