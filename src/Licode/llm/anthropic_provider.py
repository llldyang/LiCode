"""Anthropic 协议适配器。"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import anthropic
from anthropic.types import ToolUseBlock

from Licode.config import ProviderConfig

from . import (
    ROLE_ASSISTANT,
    ROLE_TOOL,
    Message,
    PromptTooLongError,
    Request,
    StreamEvent,
    ToolCall,
    ToolDefinition,
    Usage,
)


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


def _append_reminder_anthropic(messages: list[dict[str, Any]], reminder: str) -> None:
    """把 reminder 合并到末条 user 消息，保持 Anthropic 角色交替合法。"""

    reminder_block = {"type": "text", "text": reminder}
    if not messages or messages[-1]["role"] != "user":
        messages.append({"role": "user", "content": [reminder_block]})
        return
    content = messages[-1].get("content", "")
    if isinstance(content, list):
        content.append(reminder_block)
        return
    blocks: list[dict[str, Any]] = []
    if content:
        blocks.append({"type": "text", "text": content})
    blocks.append(reminder_block)
    messages[-1]["content"] = blocks


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

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        system: list[dict[str, Any]] = []
        if req.system.stable:
            system.append(
                {
                    "type": "text",
                    "text": req.system.stable,
                    "cache_control": {"type": "ephemeral"},
                }
            )
        if req.system.environment:
            system.append({"type": "text", "text": req.system.environment})
        messages = _to_anthropic_messages(req.messages)
        if req.reminder:
            _append_reminder_anthropic(messages, req.reminder)

        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "system": system,
            "messages": messages,
        }
        if req.tools:
            params["tools"] = _to_anthropic_tools(req.tools)
        has_tool_history = any(
            message.tool_calls or message.tool_results for message in req.messages
        )
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
                yield StreamEvent(
                    usage=Usage(
                        input_tokens=final_message.usage.input_tokens,
                        output_tokens=final_message.usage.output_tokens,
                        cache_write=getattr(final_message.usage, "cache_creation_input_tokens", 0)
                        or 0,
                        cache_read=getattr(final_message.usage, "cache_read_input_tokens", 0) or 0,
                    )
                )
            yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if _is_prompt_too_long(exc):
                wrapped = PromptTooLongError("anthropic prompt too long")
                wrapped.__cause__ = exc
                yield StreamEvent(err=wrapped)
            else:
                yield StreamEvent(err=exc)


def _is_prompt_too_long(error: Exception) -> bool:
    if not isinstance(error, anthropic.BadRequestError):
        return False
    body = getattr(error, "body", None)
    text = f"{error} {body}".lower()
    return "prompt is too long" in text or "context_length" in text
