"""ReAct Agent 循环编排。"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from Licode import prompt
from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    ManageInput,
    ManageOutput,
    RecoveryState,
    TriggerKind,
    manage_context,
    new_session_context,
)
from Licode.compact.const import AUTO_SAFETY_MARGIN, MANUAL_SAFETY_MARGIN, SUMMARY_RESERVE
from Licode.compact.token import estimate_tokens, usage_anchor
from Licode.conversation import Conversation
from Licode.llm import (
    PromptTooLongError,
    Provider,
    Request,
    System,
    ToolCall,
    ToolDefinition,
    ToolResult,
)
from Licode.llm import Usage as LLMUsage
from Licode.permission import Decision, Engine, Mode, Outcome
from Licode.tool import DEFAULT_TIMEOUT, Registry, Result

from .event import CompactEvent, CompactPhase, Event, Phase, ToolEvent, Usage
from .runtime import SessionRuntime

logger = logging.getLogger(__name__)

MAX_ITERATIONS: int = 25
MAX_UNKNOWN_RUN: int = 3
PLAN_REMINDER_INTERVAL: int = 4

NOTICE_MAX_ITER = "（已达最大迭代轮数 25，自动停止；可继续发消息推进。）"
NOTICE_UNKNOWN_TOOLS = "（连续多轮只请求到未注册的工具，自动停止。）"
NOTICE_STREAM_ERR = "（请求出错，本轮已中断。）"
NOTICE_CANCELLED = "（已取消。）"
EMPTY_FINAL = "（模型未生成文本答复。）"


@dataclass
class ApprovalRequest:
    """人在回路审批请求及其单次响应通道。"""

    name: str
    args: str
    reason: str
    respond: asyncio.Future[Outcome]


AgentOutput = Event | ApprovalRequest
QueueItem = TypeVar("QueueItem")


class Agent:
    """循环调用模型与工具，直到任务完成或触发停止条件。"""

    def __init__(
        self,
        provider: Provider,
        registry: Registry,
        version: str,
        engine: Engine,
        *,
        runtime: SessionRuntime | None = None,
    ) -> None:
        self._provider = provider
        self._registry = registry
        self._version = version
        self._engine = engine
        self.runtime = runtime or SessionRuntime(
            replacement=ContentReplacementState(),
            recovery=RecoveryState(),
            auto_tracking=CompactCircuitBreaker(),
            session=new_session_context("."),
        )
        self._run_lock = asyncio.Lock()

    async def run(
        self, conv: Conversation, mode: Mode, cancel: asyncio.Event
    ) -> AsyncIterator[AgentOutput]:
        async with self._run_lock:
            async for output in self._run_locked(conv, mode, cancel):
                yield output

    async def _run_locked(
        self, conv: Conversation, mode: Mode, cancel: asyncio.Event
    ) -> AsyncIterator[AgentOutput]:
        environment = await asyncio.to_thread(
            prompt.gather_environment, self._version, self._provider.model
        )
        stable_system = prompt.build_system_prompt()
        environment_text = environment.render()

        unknown_run = 0
        for iteration in range(1, MAX_ITERATIONS + 1):
            yield Event(iter=iteration)
            if cancel.is_set():
                self._ensure_assistant_tail(conv, NOTICE_CANCELLED)
                return

            if mode is Mode.PLAN:
                definitions = self._registry.read_only_definitions()
            else:
                definitions = self._registry.definitions()

            manage_input = await self._manage_input(conv, definitions, TriggerKind.AUTO)
            auto_threshold = manage_input.context_window - SUMMARY_RESERVE - AUTO_SAFETY_MARGIN
            will_summarize = (
                manage_input.context_window > SUMMARY_RESERVE + AUTO_SAFETY_MARGIN
                and manage_input.estimated_token >= auto_threshold
                and not self.runtime.auto_tracking.tripped()
            )
            if will_summarize:
                yield Event(compact=CompactEvent(phase=CompactPhase.BEFORE_AUTO))
            compact_error: Exception | None = None
            try:
                manage_output = await manage_context(manage_input)
            except Exception as exc:
                compact_error = exc
                manage_output = ManageOutput(
                    before_tokens=manage_input.estimated_token,
                    after_tokens=manage_input.estimated_token,
                )
                logger.warning("自动压缩失败，本轮继续使用可用历史: %s", exc)
            if will_summarize:
                yield Event(
                    compact=CompactEvent(
                        phase=CompactPhase.AFTER_AUTO,
                        before=manage_output.before_tokens,
                        after=manage_output.after_tokens,
                        err=compact_error,
                    )
                )

            stream_queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=1)
            reminder = ""
            if mode is Mode.PLAN:
                full = iteration == 1 or (iteration - 1) % PLAN_REMINDER_INTERVAL == 0
                reminder = prompt.plan_reminder(full)
            stream_task = asyncio.create_task(
                self._stream_once(
                    conv,
                    definitions,
                    stable_system,
                    environment_text,
                    reminder,
                    cancel,
                    stream_queue.put,
                )
            )
            try:
                async for event in self._drain(stream_task, stream_queue):
                    yield event
                text, calls, usage, stream_error = await stream_task
            finally:
                await self._stop_task(stream_task)

            if cancel.is_set():
                self._ensure_assistant_tail(conv, NOTICE_CANCELLED)
                return

            emergency_retried = False
            if isinstance(stream_error, PromptTooLongError):
                yield Event(compact=CompactEvent(phase=CompactPhase.BEFORE_EMERGENCY))
                emergency_input = await self._manage_input(
                    conv,
                    definitions,
                    TriggerKind.EMERGENCY,
                )
                try:
                    emergency_output = await manage_context(emergency_input)
                except Exception as exc:
                    yield Event(
                        compact=CompactEvent(
                            phase=CompactPhase.AFTER_EMERGENCY,
                            before=emergency_input.estimated_token,
                            err=exc,
                        )
                    )
                    yield Event(err=exc)
                    self._ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                    return
                yield Event(
                    compact=CompactEvent(
                        phase=CompactPhase.AFTER_EMERGENCY,
                        before=emergency_output.before_tokens,
                        after=emergency_output.after_tokens,
                    )
                )
                async with self.runtime._lock:
                    self.runtime.usage_anchor = 0
                    self.runtime.anchor_msg_len = 0
                    context_window = self.runtime.context_window
                estimate = estimate_tokens(0, conv.messages(), 0)
                if estimate >= context_window - MANUAL_SAFETY_MARGIN:
                    yield Event(err=stream_error)
                    self._ensure_assistant_tail(conv, NOTICE_STREAM_ERR)
                    return
                emergency_retried = True
                retry_queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=1)
                retry_task = asyncio.create_task(
                    self._stream_once(
                        conv,
                        definitions,
                        stable_system,
                        environment_text,
                        reminder,
                        cancel,
                        retry_queue.put,
                    )
                )
                try:
                    async for event in self._drain(retry_task, retry_queue):
                        yield event
                    text, calls, usage, stream_error = await retry_task
                finally:
                    await self._stop_task(retry_task)

            if stream_error is not None:
                yield Event(err=stream_error)
                fallback = NOTICE_CANCELLED if cancel.is_set() else NOTICE_STREAM_ERR
                self._ensure_assistant_tail(conv, fallback)
                return
            if emergency_retried and cancel.is_set():
                self._ensure_assistant_tail(conv, NOTICE_CANCELLED)
                return
            if usage is not None:
                yield Event(
                    usage=Usage(
                        usage.input_tokens,
                        usage.output_tokens,
                        usage.cache_write,
                        usage.cache_read,
                    )
                )

            if not calls:
                final = text or EMPTY_FINAL
                if not text:
                    yield Event(text=final)
                conv.add_assistant(final)
                await self._update_usage_anchor(conv, usage)
                yield Event(done=True)
                return

            conv.add_assistant_with_tool_calls(text, calls)
            await self._update_usage_anchor(conv, usage)
            unknown_run = unknown_run + 1 if self._all_unknown(calls) else 0

            tool_queue: asyncio.Queue[AgentOutput] = asyncio.Queue(maxsize=1)
            tool_task = asyncio.create_task(
                self._execute_batched(calls, mode, cancel, tool_queue.put)
            )
            try:
                async for output in self._drain(tool_task, tool_queue):
                    yield output
                results, completed = await tool_task
            except asyncio.CancelledError:
                cancel.set()
                try:
                    results, _ = await asyncio.shield(tool_task)
                except asyncio.CancelledError:
                    raise
                await self._record_read_files(calls, results)
                conv.add_tool_results(results)
                self._ensure_assistant_tail(conv, NOTICE_CANCELLED)
                raise
            finally:
                await self._stop_task(tool_task)
            await self._record_read_files(calls, results)
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
        stable_system: str,
        environment_text: str,
        reminder: str,
        cancel: asyncio.Event,
        push: Callable[[Event], Awaitable[None]],
    ) -> tuple[str, list[ToolCall], LLMUsage | None, Exception | None]:
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        usage: LLMUsage | None = None
        request = Request(
            messages=conv.messages(),
            tools=definitions,
            system=System(stable=stable_system, environment=environment_text),
            reminder=reminder,
        )
        stream = self._provider.stream(request).__aiter__()

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
                return "", [], None, None
            await self._stop_task(cancelled)
            try:
                stream_event = next_event.result()
            except StopAsyncIteration:
                break
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return "", [], None, exc

            if stream_event.err is not None:
                await self._close_stream(stream)
                return "", [], None, stream_event.err
            if stream_event.text:
                text_parts.append(stream_event.text)
                await push(Event(text=stream_event.text))
            if stream_event.tool_calls:
                calls.extend(stream_event.tool_calls)
            if stream_event.usage is not None:
                usage = stream_event.usage

        if cancel.is_set():
            await self._close_stream(stream)
            return "", [], None, None
        return "".join(text_parts), calls, usage, None

    async def _manage_input(
        self,
        conv: Conversation,
        definitions: list[ToolDefinition],
        trigger: TriggerKind,
    ) -> ManageInput:
        async with self.runtime._lock:
            anchor = self.runtime.usage_anchor
            anchor_len = self.runtime.anchor_msg_len
            context_window = self.runtime.context_window
        return ManageInput(
            conv=conv,
            provider=self._provider,
            context_window=context_window,
            tool_defs=definitions,
            replacement=self.runtime.replacement,
            recovery=self.runtime.recovery,
            auto_tracking=self.runtime.auto_tracking,
            session=self.runtime.session,
            usage_anchor=anchor,
            anchor_msg_len=anchor_len,
            estimated_token=estimate_tokens(anchor, conv.messages(), anchor_len),
            trigger=trigger,
        )

    async def _update_usage_anchor(
        self,
        conv: Conversation,
        usage: LLMUsage | None,
    ) -> None:
        if usage is None:
            return
        async with self.runtime._lock:
            self.runtime.usage_anchor = usage_anchor(usage)
            self.runtime.anchor_msg_len = conv.length()

    async def _record_read_files(
        self,
        calls: list[ToolCall],
        results: list[ToolResult],
    ) -> None:
        result_by_id = {result.tool_call_id: result for result in results}
        for call in calls:
            result = result_by_id.get(call.id)
            if call.name != "read_file" or result is None or result.is_error:
                continue
            try:
                args = json.loads(call.input or "{}")
            except (json.JSONDecodeError, TypeError):
                continue
            path_value = args.get("path") if isinstance(args, dict) else None
            if not isinstance(path_value, str) or not path_value:
                continue
            try:
                path = Path(path_value).resolve()
                data = await asyncio.to_thread(path.read_bytes)
            except OSError:
                continue
            self.runtime.recovery.record_file(
                str(path),
                data.decode("utf-8", errors="replace"),
            )

    async def run_force_compact(
        self,
        conv: Conversation,
        tool_defs: list[ToolDefinition],
    ) -> tuple[int, int]:
        """在主循环空闲时无条件执行一次手动摘要。"""

        async with self._run_lock:
            manage_input = await self._manage_input(
                conv,
                tool_defs,
                TriggerKind.MANUAL,
            )
            output = await manage_context(manage_input)
            async with self.runtime._lock:
                self.runtime.usage_anchor = 0
                self.runtime.anchor_msg_len = 0
            return output.before_tokens, output.after_tokens

    async def _execute_batched(
        self,
        calls: list[ToolCall],
        mode: Mode,
        cancel: asyncio.Event,
        push: Callable[[AgentOutput], Awaitable[None]],
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
                allowed: list[tuple[int, ToolCall]] = []
                for call_index in range(index, end):
                    decision, reason = self._engine.check(mode, calls[call_index], True)
                    if decision is Decision.ALLOW:
                        allowed.append((call_index, calls[call_index]))
                    else:
                        results[call_index] = ToolResult(
                            tool_call_id=calls[call_index].id,
                            content=reason or "只读工具调用未获权限",
                            is_error=True,
                        )
                outcomes = await asyncio.gather(
                    *(self._run_one(call, cancel) for _, call in allowed)
                )
                completed = True
                for (call_index, call), (result, one_completed) in zip(
                    allowed, outcomes, strict=True
                ):
                    results[call_index] = self._tool_result(call, result)
                    completed = completed and one_completed
                for call_index in range(index, end):
                    stored_result = results[call_index]
                    if stored_result is not None:
                        await push(self._end_result_event(calls[call_index], stored_result))
                if not completed:
                    self._fill_cancelled(results, calls, end)
                    return self._complete_results(results), False
                index = end
                continue

            call = calls[index]
            await push(self._start_event(call))
            decision, reason = self._engine.check(mode, call, False)
            completed = True
            if decision is Decision.DENY:
                result = Result(reason, is_error=True)
            elif decision is Decision.ALLOW:
                result, completed = await self._run_one(call, cancel)
            else:
                try:
                    outcome = await self._request_approval(call, reason, cancel, push)
                except asyncio.CancelledError:
                    result = Result(NOTICE_CANCELLED, is_error=True)
                    completed = False
                else:
                    if outcome is Outcome.DENY_ONCE:
                        result = Result("用户拒绝本次工具调用", is_error=True)
                    else:
                        if outcome is Outcome.ALLOW_FOREVER:
                            try:
                                self._engine.persist_local_allow(call)
                            except Exception as exc:
                                logger.warning("永久权限规则写入失败: %s", exc)
                        result, completed = await self._run_one(call, cancel)
            tool_result = self._tool_result(call, result)
            results[index] = tool_result
            await push(self._end_result_event(call, tool_result))
            index += 1
            if not completed:
                self._fill_cancelled(results, calls, index)
                return self._complete_results(results), False

        return self._complete_results(results), True

    async def _request_approval(
        self,
        call: ToolCall,
        reason: str,
        cancel: asyncio.Event,
        push: Callable[[AgentOutput], Awaitable[None]],
    ) -> Outcome:
        respond: asyncio.Future[Outcome] = asyncio.get_running_loop().create_future()
        await push(
            ApprovalRequest(
                name=call.name,
                args=self._preview(call.input),
                reason=reason,
                respond=respond,
            )
        )
        cancelled = asyncio.create_task(cancel.wait())
        waiters: set[asyncio.Future[Any]] = {respond, cancelled}
        try:
            done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
            if cancel.is_set() or respond not in done:
                raise asyncio.CancelledError
            return respond.result()
        finally:
            if not respond.done():
                respond.cancel()
            await self._stop_task(cancelled)

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
        self, task: asyncio.Future[Any], queue: asyncio.Queue[QueueItem]
    ) -> AsyncIterator[QueueItem]:
        while not task.done() or not queue.empty():
            if not queue.empty():
                yield queue.get_nowait()
                continue
            queued = asyncio.create_task(queue.get())
            try:
                done, _ = await asyncio.wait({task, queued}, return_when=asyncio.FIRST_COMPLETED)
                if queued in done:
                    yield queued.result()
            finally:
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

    @classmethod
    def _end_result_event(cls, call: ToolCall, result: ToolResult) -> Event:
        return cls._end_event(call, Result(result.content, result.is_error))

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


def new_agent(
    provider: Provider,
    registry: Registry,
    version: str,
    engine: Engine,
    *,
    runtime: SessionRuntime | None = None,
) -> Agent:
    return Agent(provider, registry, version, engine, runtime=runtime)


__all__ = [
    "MAX_ITERATIONS",
    "MAX_UNKNOWN_RUN",
    "AgentOutput",
    "NOTICE_CANCELLED",
    "NOTICE_MAX_ITER",
    "NOTICE_STREAM_ERR",
    "NOTICE_UNKNOWN_TOOLS",
    "PLAN_REMINDER_INTERVAL",
    "ApprovalRequest",
    "Agent",
    "CompactEvent",
    "CompactPhase",
    "Event",
    "Phase",
    "ToolEvent",
    "Usage",
    "SessionRuntime",
    "new_agent",
]
