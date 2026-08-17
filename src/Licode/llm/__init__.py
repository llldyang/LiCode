"""协议无关的 LLM 数据类型与 provider 工厂。"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol

from Licode.config import ProviderConfig


@dataclass
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass
class StreamEvent:
    text: str = ""
    done: bool = False
    err: Exception | None = None


class Provider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    def stream(self, msgs: list[Message]) -> AsyncIterator[StreamEvent]: ...


def new_provider(cfg: ProviderConfig) -> Provider:
    """按协议构造对应的 provider。"""

    if cfg.protocol == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(cfg)
    if cfg.protocol == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(cfg)
    raise ValueError(f"不支持的协议: {cfg.protocol}")


__all__ = ["Message", "Provider", "StreamEvent", "new_provider"]
