"""OpenAI Chat Completions 协议适配器。"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

import openai
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk, ChatCompletionMessageParam

from Licode.config import ProviderConfig

from . import (
    ROLE_ASSISTANT,
    ROLE_TOOL,
    Request,
    StreamEvent,
    ToolCall,
    ToolDefinition,
    Usage,
)


def _to_openai_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


def _to_openai_messages(req: Request) -> list[ChatCompletionMessageParam]:
    system = req.system.stable
    if req.system.environment:
        system += "\n\n" + req.system.environment
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for message in req.messages:
        if message.role == ROLE_TOOL:
            messages.extend(
                {
                    "role": "tool",
                    "tool_call_id": result.tool_call_id,
                    "content": result.content,
                }
                for result in message.tool_results
            )
            continue
        if message.role == ROLE_ASSISTANT and message.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": message.content or None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": call.input or "{}",
                            },
                        }
                        for call in message.tool_calls
                    ],
                }
            )
            continue
        messages.append({"role": message.role, "content": message.content})
    if req.reminder:
        messages.append({"role": "user", "content": req.reminder})
    return cast(list[ChatCompletionMessageParam], messages)


class OpenAIProvider:
    def __init__(self, cfg: ProviderConfig) -> None:
        self._client = openai.AsyncOpenAI(
            api_key=cfg.api_key,
            base_url=cfg.base_url or None,
        )
        self._name = cfg.name
        self._model = cfg.model

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        params: dict[str, Any] = {
            "model": self._model,
            "messages": _to_openai_messages(req),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if req.tools:
            params["tools"] = _to_openai_tools(req.tools)
        try:
            stream = cast(
                AsyncStream[ChatCompletionChunk],
                await self._client.chat.completions.create(**params),
            )
            tool_calls_buffer: dict[int, dict[str, str]] = {}
            finish_reason: str | None = None
            async for chunk in stream:
                if not chunk.choices:
                    if chunk.usage is not None:
                        yield StreamEvent(
                            usage=Usage(
                                input_tokens=chunk.usage.prompt_tokens,
                                output_tokens=chunk.usage.completion_tokens,
                                cache_read=getattr(
                                    getattr(chunk.usage, "prompt_tokens_details", None),
                                    "cached_tokens",
                                    0,
                                )
                                or 0,
                            )
                        )
                    continue
                choice = chunk.choices[0]
                finish_reason = choice.finish_reason or finish_reason
                text = choice.delta.content
                if text:
                    yield StreamEvent(text=text)
                for tool_call in choice.delta.tool_calls or []:
                    buffer = tool_calls_buffer.setdefault(tool_call.index, {})
                    if tool_call.id:
                        buffer["id"] = tool_call.id
                    function = tool_call.function
                    if function is not None:
                        if function.name:
                            buffer["name"] = function.name
                        if function.arguments:
                            buffer["args"] = buffer.get("args", "") + function.arguments
            if finish_reason == "tool_calls" or tool_calls_buffer:
                calls = [
                    ToolCall(
                        id=value.get("id", ""),
                        name=value.get("name", ""),
                        input=value.get("args") or "{}",
                    )
                    for _, value in sorted(tool_calls_buffer.items())
                ]
                if calls:
                    yield StreamEvent(tool_calls=calls)
            yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield StreamEvent(err=exc)
