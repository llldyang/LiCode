"""协议无关的 LLM 数据类型与 provider 工厂。"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from Licode.config import ProviderConfig

ROLE_USER: Literal["user"] = "user"
ROLE_ASSISTANT: Literal["assistant"] = "assistant"
ROLE_TOOL: Literal["tool"] = "tool"


@dataclass
class ToolCall:
    """协议无关地承载模型发起的一次工具调用。"""

    id: str
    name: str
    input: str


@dataclass
class ToolResult:
    """协议无关地承载一次工具执行结果。"""

    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass
class ToolDefinition:
    """注册中心导出的协议无关工具定义。"""

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class Usage:
    """一轮请求的 token 用量与缓存命中信息。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_write: int = 0
    cache_read: int = 0


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass
class System:
    """分离稳定缓存块与动态环境块的系统上下文。"""

    stable: str = ""
    environment: str = ""


@dataclass
class Request:
    """Provider 发起一轮流式请求所需的协议无关数据。"""

    messages: list[Message] = field(default_factory=list)
    tools: list[ToolDefinition] = field(default_factory=list)
    system: System = field(default_factory=System)
    reminder: str = ""


@dataclass
class StreamEvent:
    """Provider 流中的正文、工具调用、用量、结束或错误事件。"""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage | None = None
    done: bool = False
    err: Exception | None = None


class Provider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    def stream(self, req: Request) -> AsyncIterator[StreamEvent]: ...


def new_provider(cfg: ProviderConfig) -> Provider:
    """按协议构造对应的 provider。"""

    if cfg.protocol == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(cfg)
    if cfg.protocol == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(cfg)
    raise ValueError(f"不支持的协议: {cfg.protocol}")


__all__ = [
    "ROLE_ASSISTANT",
    "ROLE_TOOL",
    "ROLE_USER",
    "Message",
    "Provider",
    "Request",
    "StreamEvent",
    "System",
    "ToolCall",
    "ToolDefinition",
    "ToolResult",
    "Usage",
    "new_provider",
]
