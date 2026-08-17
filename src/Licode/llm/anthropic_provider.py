"""Anthropic 协议适配器。"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import anthropic
from anthropic.types import ToolUseBlock

from Licode.config import ProviderConfig
from Licode.prompt import SYSTEM_PROMPT

from . import ROLE_ASSISTANT, ROLE_TOOL, Message, StreamEvent, ToolCall, ToolDefinition


def _to_anthropic_tools(tools: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        for tool in tools
    ]


def _to_anthropic_messages(msgs: list[Message]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for message in msgs:
        if message.role == ROLE_TOOL:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": result.tool_call_id,
                            "content": result.content,
                            "is_error": result.is_error,
                        }
                        for result in message.tool_results
                    ],
                }
            )
            continue
        if message.role == ROLE_ASSISTANT and message.tool_calls:
            content: list[dict[str, Any]] = []
            if message.content:
                content.append({"type": "text", "text": message.content})
            for call in message.tool_calls:
                try:
                    tool_input = json.loads(call.input or "{}")
                except json.JSONDecodeError:
                    tool_input = {}
                content.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": tool_input,
                    }
                )
            messages.append({"role": "assistant", "content": content})
            continue
        messages.append({"role": message.role, "content": message.content})
    return messages


class AnthropicProvider:
    def __init__(self, cfg: ProviderConfig) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=cfg.api_key,
            base_url=cfg.base_url or None,
        )
        self._name = cfg.name
        self._model = cfg.model
        self._thinking = cfg.thinking

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    async def stream(
        self, msgs: list[Message], tools: list[ToolDefinition]
    ) -> AsyncIterator[StreamEvent]:
        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "system": SYSTEM_PROMPT,
            "messages": _to_anthropic_messages(msgs),
        }
        if tools:
            params["tools"] = _to_anthropic_tools(tools)
        has_tool_history = any(message.tool_calls or message.tool_results for message in msgs)
        if self._thinking and not has_tool_history:
            params["thinking"] = {"type": "enabled", "budget_tokens": 2048}

        try:
            async with self._client.messages.stream(**params) as stream:
                async for event in stream:
                    if event.type != "content_block_delta":
                        continue
                    delta = event.delta
                    if getattr(delta, "type", "") == "text_delta":
                        text = getattr(delta, "text", "")
                        if text:
                            yield StreamEvent(text=text)
                    # thinking_delta 按需求接收后丢弃。
                final_message = await stream.get_final_message()
                if getattr(final_message, "stop_reason", None) == "tool_use":
                    calls = [
                        ToolCall(
                            id=block.id,
                            name=block.name,
                            input=json.dumps(block.input, ensure_ascii=False),
                        )
                        for block in final_message.content
                        if isinstance(block, ToolUseBlock)
                    ]
                    if calls:
                        yield StreamEvent(tool_calls=calls)
            yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield StreamEvent(err=exc)
