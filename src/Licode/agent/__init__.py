"""ReAct Agent 循环编排。"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from Licode import prompt
from Licode.conversation import Conversation
from Licode.llm import Provider, ToolCall, ToolDefinition, ToolResult
from Licode.llm import Usage as LLMUsage
from Licode.tool import DEFAULT_TIMEOUT, Registry, Result

MAX_ITERATIONS: int = 25
MAX_UNKNOWN_RUN: int = 3

NOTICE_MAX_ITER = "（已达最大迭代轮数 25，自动停止；可继续发消息推进。）"
NOTICE_UNKNOWN_TOOLS = "（连续多轮只请求到未注册的工具，自动停止。）"
NOTICE_STREAM_ERR = "（请求出错，本轮已中断。）"
NOTICE_CANCELLED = "（已取消。）"
EMPTY_FINAL = "（模型未生成文本答复。）"


class Phase(IntEnum):
    START = 0
    END = 1


class Mode(IntEnum):
    NORMAL = 0
    PLAN = 1


@dataclass
class Usage:
    """一轮请求的输入与输出 token 用量。"""

    input: int = 0
    output: int = 0


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
    """Agent Loop 向界面输出的统一事件。"""

    text: str = ""
    tool: ToolEvent | None = None
    usage: Usage | None = None
    iter: int = 0
    notice: str = ""
    done: bool = False
    err: Exception | None = None


class Agent:
    """循环调用模型与工具，直到任务完成或触发停止条件。"""

    def __init__(self, provider: Provider, registry: Registry) -> None:
        self._provider = provider
        self._registry = registry

    async def run(
        self, conv: Conversation, mode: Mode, cancel: asyncio.Event
    ) -> AsyncIterator[Event]:
        if mode is Mode.PLAN:
            definitions = self._registry.read_only_definitions()
            system_suffix = prompt.PLAN_MODE_REMINDER
        else:
            definitions = self._registry.definitions()
            system_suffix = ""

        unknown_run = 0
        for iteration in range(1, MAX_ITERATIONS + 1):
            yield Event(iter=iteration)
            if cancel.is_set():
                self._ensure_assistant_tail(conv, NOTICE_CANCELLED)
                return

            stream_queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=1)
            stream_task = asyncio.create_task(
                self._stream_once(
                    conv,
                    definitions,
                    system_suffix,
                    cancel,
                    stream_queue.put,
                )
            )
            try:
                async for event in self._drain(stream_task, stream_queue):
                    yield event
                text, calls, usage, ok = await stream_task
            finally:
                await self._stop_task(stream_task)

            if not ok:
                fallback = NOTICE_CANCELLED if cancel.is_set() else NOTICE_STREAM_ERR
                self._ensure_assistant_tail(conv, fallback)
                return
            if usage is not None:
                yield Event(usage=Usage(usage.input_tokens, usage.output_tokens))

            if not calls:
                final = text or EMPTY_FINAL
                if not text:
                    yield Event(text=final)
                conv.add_assistant(final)
                yield Event(done=True)
                return

            conv.add_assistant_with_tool_calls(text, calls)
            unknown_run = unknown_run + 1 if self._all_unknown(calls) else 0

            tool_queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=1)
            tool_task = asyncio.create_task(self._execute_batched(calls, cancel, tool_queue.put))
            try:
                async for event in self._drain(tool_task, tool_queue):
                    yield event
                results, completed = await tool_task
            finally:
                await self._stop_task(tool_task)
            conv.add_tool_results(results)

            if not completed:
                self._ensure_assistant_tail(conv, NOTICE_CANCELLED)
                return
            if unknown_run >= MAX_UNKNOWN_RUN:
                yield Event(notice=NOTICE_UNKNOWN_TOOLS)
                self._ensure_assistant_tail(conv, NOTICE_UNKNOWN_TOOLS)
                yield Event(done=True)
                return

        yield Event(notice=NOTICE_MAX_ITER)
        self._ensure_assistant_tail(conv, NOTICE_MAX_ITER)
        yield Event(done=True)

    async def _stream_once(
        self,
        conv: Conversation,
        definitions: list[ToolDefinition],
        system_suffix: str,
        cancel: asyncio.Event,
        push: Callable[[Event], Awaitable[None]],
    ) -> tuple[str, list[ToolCall], LLMUsage | None, bool]:
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        usage: LLMUsage | None = None
        stream = self._provider.stream(conv.messages(), definitions, system_suffix).__aiter__()

        while not cancel.is_set():
            next_event: asyncio.Future[Any] = asyncio.ensure_future(anext(stream))
            cancelled: asyncio.Future[Any] = asyncio.ensure_future(cancel.wait())
            done, _ = await asyncio.wait(
                {next_event, cancelled}, return_when=asyncio.FIRST_COMPLETED
            )
            if next_event not in done:
                await self._stop_task(next_event)
                await self._stop_task(cancelled)
                await self._close_stream(stream)
                return "", [], None, False
            await self._stop_task(cancelled)
            try:
                stream_event = next_event.result()
            except StopAsyncIteration:
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await push(Event(err=exc))
                return "", [], None, False

            if stream_event.err is not None:
                await push(Event(err=stream_event.err))
                await self._close_stream(stream)
                return "", [], None, False
            if stream_event.text:
                text_parts.append(stream_event.text)
                await push(Event(text=stream_event.text))
            if stream_event.tool_calls:
                calls.extend(stream_event.tool_calls)
            if stream_event.usage is not None:
                usage = stream_event.usage

        if cancel.is_set():
            await self._close_stream(stream)
            return "", [], None, False
        return "".join(text_parts), calls, usage, True

    async def _execute_batched(
        self,
        calls: list[ToolCall],
        cancel: asyncio.Event,
        push: Callable[[Event], Awaitable[None]],
    ) -> tuple[list[ToolResult], bool]:
        results: list[ToolResult | None] = [None] * len(calls)
        index = 0
        while index < len(calls):
            if cancel.is_set():
                self._fill_cancelled(results, calls, index)
                return self._complete_results(results), False

            if self._registry.is_read_only(calls[index].name):
                end = index + 1
                while end < len(calls) and self._registry.is_read_only(calls[end].name):
                    end += 1
                for call in calls[index:end]:
                    await push(self._start_event(call))
                outcomes = await asyncio.gather(
                    *(self._run_one(call, cancel) for call in calls[index:end])
                )
                completed = True
                for offset, (result, one_completed) in enumerate(outcomes):
                    call_index = index + offset
                    results[call_index] = self._tool_result(calls[call_index], result)
                    await push(self._end_event(calls[call_index], result))
                    completed = completed and one_completed
                if not completed:
                    self._fill_cancelled(results, calls, end)
                    return self._complete_results(results), False
                index = end
                continue

            call = calls[index]
            await push(self._start_event(call))
            result, completed = await self._run_one(call, cancel)
            results[index] = self._tool_result(call, result)
            await push(self._end_event(call, result))
            index += 1
            if not completed:
                self._fill_cancelled(results, calls, index)
                return self._complete_results(results), False

        return self._complete_results(results), True

    async def _run_one(self, call: ToolCall, cancel: asyncio.Event) -> tuple[Result, bool]:
        if cancel.is_set():
            return Result(NOTICE_CANCELLED, is_error=True), False
        execution = asyncio.create_task(
            asyncio.wait_for(
                self._registry.execute(call.name, call.input, DEFAULT_TIMEOUT),
                timeout=DEFAULT_TIMEOUT,
            )
        )
        cancelled = asyncio.create_task(cancel.wait())
        done, _ = await asyncio.wait({execution, cancelled}, return_when=asyncio.FIRST_COMPLETED)
        if execution in done:
            await self._stop_task(cancelled)
            try:
                return execution.result(), True
            except TimeoutError:
                return (
                    Result(
                        f"工具 {call.name} 执行超时（{DEFAULT_TIMEOUT}s）",
                        is_error=True,
                    ),
                    True,
                )
        await self._stop_task(execution)
        await self._stop_task(cancelled)
        return Result(NOTICE_CANCELLED, is_error=True), False

    async def _drain(
        self, task: asyncio.Future[Any], queue: asyncio.Queue[Event]
    ) -> AsyncIterator[Event]:
        while not task.done() or not queue.empty():
            if not queue.empty():
                yield queue.get_nowait()
                continue
            queued = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({task, queued}, return_when=asyncio.FIRST_COMPLETED)
            if queued in done:
                yield queued.result()
            else:
                await self._stop_task(queued)

    def _all_unknown(self, calls: list[ToolCall]) -> bool:
        return all(self._registry.get(call.name) is None for call in calls)

    @staticmethod
    def _ensure_assistant_tail(conv: Conversation, fallback: str) -> None:
        if conv.last_role() != "assistant":
            conv.add_assistant(fallback)

    @staticmethod
    def _fill_cancelled(
        results: list[ToolResult | None], calls: list[ToolCall], start: int
    ) -> None:
        for index in range(start, len(calls)):
            if results[index] is None:
                results[index] = ToolResult(
                    tool_call_id=calls[index].id,
                    content=NOTICE_CANCELLED,
                    is_error=True,
                )

    @staticmethod
    def _complete_results(results: list[ToolResult | None]) -> list[ToolResult]:
        return [result for result in results if result is not None]

    @classmethod
    def _start_event(cls, call: ToolCall) -> Event:
        return Event(tool=ToolEvent(name=call.name, args=cls._preview(call.input)))

    @classmethod
    def _end_event(cls, call: ToolCall, result: Result) -> Event:
        return Event(
            tool=ToolEvent(
                name=call.name,
                args=cls._preview(call.input),
                phase=Phase.END,
                result=result.content,
                is_error=result.is_error,
            )
        )

    @staticmethod
    def _tool_result(call: ToolCall, result: Result) -> ToolResult:
        return ToolResult(
            tool_call_id=call.id,
            content=result.content,
            is_error=result.is_error,
        )

    @staticmethod
    def _preview(args: str) -> str:
        normalized = args or "{}"
        if len(normalized) <= 60:
            return normalized
        return normalized[:57] + "..."

    @staticmethod
    async def _stop_task(task: asyncio.Future[Any]) -> None:
        if task.done():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    @staticmethod
    async def _close_stream(stream: AsyncIterator[Any]) -> None:
        close = getattr(stream, "aclose", None)
        if close is not None:
            with suppress(asyncio.CancelledError):
                await close()


__all__ = [
    "MAX_ITERATIONS",
    "MAX_UNKNOWN_RUN",
    "NOTICE_CANCELLED",
    "NOTICE_MAX_ITER",
    "NOTICE_STREAM_ERR",
    "NOTICE_UNKNOWN_TOOLS",
    "Agent",
    "Event",
    "Mode",
    "Phase",
    "ToolEvent",
    "Usage",
]
