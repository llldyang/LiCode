"""单轮工具闭环编排。"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from enum import Enum

from Licode.conversation import Conversation
from Licode.llm import Provider, ToolResult
from Licode.tool import DEFAULT_TIMEOUT, Registry


class Phase(Enum):
    START = "start"
    END = "end"


@dataclass
class ToolEvent:
    """供界面渲染的一次工具开始或结束事件。"""

    name: str
    args: str = ""
    phase: Phase = Phase.START
    result: str = ""
    is_error: bool = False


@dataclass
class Event:
    """单轮闭环向界面输出的统一事件。"""

    text: str = ""
    tool: ToolEvent | None = None
    done: bool = False
    err: Exception | None = None


class Agent:
    """执行一次请求、一次工具批次和一次续答。"""

    def __init__(self, provider: Provider, registry: Registry) -> None:
        self._provider = provider
        self._registry = registry

    async def run(self, conv: Conversation) -> AsyncIterator[Event]:
        definitions = self._registry.definitions()
        preamble_parts: list[str] = []
        calls = []

        async for stream_event in self._provider.stream(conv.messages(), definitions):
            if stream_event.err is not None:
                yield Event(err=stream_event.err)
                return
            if stream_event.text:
                preamble_parts.append(stream_event.text)
                yield Event(text=stream_event.text)
            if stream_event.tool_calls:
                calls.extend(stream_event.tool_calls)

        preamble = "".join(preamble_parts)
        if not calls:
            conv.add_assistant(preamble)
            yield Event(done=True)
            return

        conv.add_assistant_with_tool_calls(preamble, calls)
        results: list[ToolResult] = []
        for call in calls:
            args_preview = self._preview(call.input)
            yield Event(tool=ToolEvent(name=call.name, args=args_preview))
            result = await self._registry.execute(call.name, call.input, timeout=DEFAULT_TIMEOUT)
            yield Event(
                tool=ToolEvent(
                    name=call.name,
                    args=args_preview,
                    phase=Phase.END,
                    result=result.content,
                    is_error=result.is_error,
                )
            )
            results.append(
                ToolResult(
                    tool_call_id=call.id,
                    content=result.content,
                    is_error=result.is_error,
                )
            )
        conv.add_tool_results(results)

        final_parts: list[str] = []
        async for stream_event in self._provider.stream(conv.messages(), definitions):
            if stream_event.err is not None:
                yield Event(err=stream_event.err)
                return
            if stream_event.text:
                final_parts.append(stream_event.text)
                yield Event(text=stream_event.text)
            # 本章到续答即停止，续答里的工具调用交由下一章处理。

        final = "".join(final_parts)
        if not final:
            final = "已达到本章的单轮工具调用上限。"
            yield Event(text=final)
        conv.add_assistant(final)
        yield Event(done=True)

    @staticmethod
    def _preview(args: str) -> str:
        normalized = args or "{}"
        if len(normalized) <= 60:
            return normalized
        return normalized[:57] + "..."


__all__ = ["Agent", "Event", "Phase", "ToolEvent"]
