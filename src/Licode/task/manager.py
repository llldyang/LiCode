"""进程内后台 SubAgent 任务管理器。"""

from __future__ import annotations

import asyncio
import secrets
import sys
import time
from contextlib import suppress
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING

from Licode.agent import ApprovalRequest, Event, Phase
from Licode.agent.fork import is_fork_context
from Licode.permission import Outcome

if TYPE_CHECKING:
    from Licode.agent import Agent, AgentOutput
    from Licode.conversation import Conversation


class Status(IntEnum):
    RUNNING = 0
    COMPLETED = 1
    FAILED = 2
    CANCELLED = 3

    def __str__(self) -> str:
        return self.name.lower()


RUNNING = Status.RUNNING
COMPLETED = Status.COMPLETED
FAILED = Status.FAILED
CANCELLED = Status.CANCELLED


@dataclass
class Usage:
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0


@dataclass
class BackgroundTask:
    """一个后台子 Agent 的完整状态快照。"""

    id: str
    name: str
    sub_agent: Agent
    conv: Conversation
    task: str
    status: Status = Status.RUNNING
    result: str = ""
    err: BaseException | None = None
    start_time: float = field(default_factory=time.monotonic)
    end_time: float = 0.0
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    handle: asyncio.Task[str] | None = None
    usage: Usage = field(default_factory=Usage)
    tool_count: int = 0
    last_activity: str = ""


@dataclass
class PartialState:
    """前台运行移交后台时已经收集的进度。"""

    last_assistant_text: str = ""
    tool_count: int = 0
    last_activity: str = ""
    usage: Usage = field(default_factory=Usage)


class TaskNotFound(LookupError):
    """按 id 或 name 找不到任务。"""


class TaskBusy(RuntimeError):
    """任务尚未完成，不能续派。"""


class Manager:
    """管理当前进程中的后台 SubAgent。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._tasks: dict[str, BackgroundTask] = {}
        self._by_name: dict[str, str] = {}
        self._done: asyncio.Queue[str] = asyncio.Queue(maxsize=32)
        self._approvals: asyncio.Queue[ApprovalRequest] = asyncio.Queue(maxsize=32)
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"task_{secrets.token_hex(4)}"

    def get(self, task_id: str) -> BackgroundTask | None:
        return self._tasks.get(task_id)

    def list(self) -> list[BackgroundTask]:
        return sorted(self._tasks.values(), key=lambda item: item.start_time)

    def subscribe_done(self) -> asyncio.Queue[str]:
        return self._done

    def subscribe_approvals(self) -> asyncio.Queue[ApprovalRequest]:
        return self._approvals

    async def _register(self, task: BackgroundTask) -> None:
        async with self._lock:
            self._tasks[task.id] = task
            if task.name:
                self._by_name[task.name] = task.id

    def _notify_done(self, task_id: str) -> None:
        try:
            self._done.put_nowait(task_id)
        except asyncio.QueueFull:
            print(
                f"task manager: done queue full, dropping notification for {task_id}",
                file=sys.stderr,
            )

    async def _aggregate_task_events(
        self,
        events: asyncio.Queue[AgentOutput | None],
        task: BackgroundTask,
    ) -> None:
        while True:
            output = await events.get()
            if output is None:
                return
            if not isinstance(output, Event):
                continue
            if output.text:
                task.last_activity = output.text[-120:]
            if output.tool is not None and output.tool.phase is Phase.START:
                task.tool_count += 1
                task.last_activity = output.tool.name
            if output.usage is not None:
                task.usage.input += output.usage.input
                task.usage.output += output.usage.output
                task.usage.cache_write += output.usage.cache_write
                task.usage.cache_read += output.usage.cache_read

    async def _finish_runner(
        self,
        task: BackgroundTask,
        events: asyncio.Queue[AgentOutput | None],
        handle: asyncio.Task[str],
        aggregator: asyncio.Task[None],
    ) -> None:
        try:
            task.result = await handle
            task.status = Status.COMPLETED
        except asyncio.CancelledError:
            task.status = Status.CANCELLED
        except BaseException as exc:
            task.status = Status.FAILED
            task.err = exc
        finally:
            task.end_time = time.monotonic()
            with suppress(asyncio.QueueFull):
                events.put_nowait(None)
            with suppress(asyncio.CancelledError):
                await aggregator
            self._notify_done(task.id)

    async def launch(
        self,
        agent: Agent,
        conv: Conversation,
        name: str,
        task_text: str,
    ) -> str:
        task = BackgroundTask(
            id=self._next_id(),
            name=name,
            sub_agent=agent,
            conv=conv,
            task=task_text,
        )
        await self._register(task)
        events: asyncio.Queue[AgentOutput | None] = asyncio.Queue(maxsize=64)
        aggregator = asyncio.create_task(self._aggregate_task_events(events, task))
        run_task_text = "" if is_fork_context(conv.messages()) else task_text
        run_handle = asyncio.create_task(agent.run_to_completion(conv, run_task_text, events))
        task.handle = run_handle
        asyncio.create_task(self._finish_runner(task, events, run_handle, aggregator))
        return task.id

    async def adopt_running(
        self,
        agent: Agent,
        conv: Conversation,
        name: str,
        events: asyncio.Queue[AgentOutput | None],
        handle: asyncio.Task[str],
        partial: PartialState,
        task_text: str = "",
    ) -> str:
        task = BackgroundTask(
            id=self._next_id(),
            name=name,
            sub_agent=agent,
            conv=conv,
            task=task_text,
            usage=Usage(
                partial.usage.input,
                partial.usage.output,
                partial.usage.cache_write,
                partial.usage.cache_read,
            ),
            tool_count=partial.tool_count,
            last_activity=partial.last_activity or partial.last_assistant_text,
            handle=handle,
        )
        await self._register(task)
        aggregator = asyncio.create_task(self._aggregate_task_events(events, task))
        asyncio.create_task(self._finish_runner(task, events, handle, aggregator))
        return task.id

    async def stop(self, task_id: str) -> bool:
        task = self.get(task_id)
        if task is None:
            return False
        if task.handle is not None and not task.handle.done():
            task.cancel_event.set()
            task.handle.cancel()
            with suppress(asyncio.CancelledError):
                await task.handle
            await asyncio.sleep(0)
        return True

    async def send_message(self, name: str, message: str) -> str:
        task_id = self._by_name.get(name)
        task = self.get(task_id) if task_id is not None else None
        if task is None:
            raise TaskNotFound(f"unknown task name: {name}")
        if task.status is not Status.COMPLETED:
            raise TaskBusy(f"task is not completed: {name}")
        task.conv.add_user(message)
        task.status = Status.RUNNING
        task.result = ""
        task.err = None
        events: asyncio.Queue[AgentOutput | None] = asyncio.Queue(maxsize=64)
        aggregator = asyncio.create_task(self._aggregate_task_events(events, task))
        handle = asyncio.create_task(task.sub_agent.run_to_completion(task.conv, "", events))
        task.handle = handle
        asyncio.create_task(self._finish_runner(task, events, handle, aggregator))
        return task.id

    async def upgrade_approval(self, request: ApprovalRequest) -> tuple[Outcome, bool]:
        """把子 Agent 审批请求交给 TUI，并等待用户选择。"""

        await self._approvals.put(request)
        try:
            outcome = await request.respond
        except asyncio.CancelledError:
            return Outcome.DENY_ONCE, False
        return outcome, True
