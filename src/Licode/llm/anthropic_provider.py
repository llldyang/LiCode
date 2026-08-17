"""Anthropic 协议适配器。"""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import anthropic

from Licode.config import ProviderConfig
from Licode.prompt import SYSTEM_PROMPT

from . import Message, StreamEvent


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

    async def stream(self, msgs: list[Message]) -> AsyncIterator[StreamEvent]:
        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": 4096,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": message.role, "content": message.content} for message in msgs],
        }
        if self._thinking:
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
            yield StreamEvent(done=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            yield StreamEvent(err=exc)
