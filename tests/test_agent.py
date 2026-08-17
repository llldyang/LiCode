import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from Licode import prompt
from Licode.agent import (
    MAX_ITERATIONS,
    MAX_UNKNOWN_RUN,
    NOTICE_CANCELLED,
    NOTICE_MAX_ITER,
    NOTICE_STREAM_ERR,
    NOTICE_UNKNOWN_TOOLS,
    PLAN_REMINDER_INTERVAL,
    Agent,
    ApprovalRequest,
    Phase,
)
from Licode.conversation import Conversation
from Licode.llm import Message, Request, StreamEvent, ToolCall, ToolDefinition, Usage
from Licode.permission import Decision, Engine, Mode, Outcome, new_engine
from Licode.tool import Registry, Result, new_default_registry


class FakeProvider:
    def __init__(self, scripts: list[list[StreamEvent]], repeat_last: bool = False) -> None:
        self.scripts = scripts
        self.repeat_last = repeat_last
        self.call_count = 0
        self.requests: list[Request] = []
        self.histories: list[list[Message]] = []
        self.tool_definitions: list[list[ToolDefinition]] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    async def stream(self, req: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(req)
        self.histories.append(req.messages)
        self.tool_definitions.append(req.tools)
        index = self.call_count
        self.call_count += 1
        if self.repeat_last:
            index = min(index, len(self.scripts) - 1)
        for event in self.scripts[index]:
            yield event


class ProbeTool:
    read_only = True

    def name(self) -> str:
        return "probe"

    def description(self) -> str:
        return "测试只读工具"

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        return Result(content="probe:" + (args or "{}"))


def tool_event(call_id: str, name: str = "probe", args: str = "{}") -> list[StreamEvent]:
    return [
        StreamEvent(tool_calls=[ToolCall(id=call_id, name=name, input=args)]),
        StreamEvent(usage=Usage(10, 2)),
        StreamEvent(done=True),
    ]


def registry_with_probe() -> Registry:
    registry = Registry()
    registry.register(ProbeTool())
    return registry


def permission_engine(root: Path | None = None) -> Engine:
    base = (root or Path.cwd()).resolve()
    return Engine(
        root=str(base),
        local_path=str(base / ".Licode" / "settings.local.yaml"),
    )


@pytest.mark.asyncio
async def test_agent_runs_multiple_iterations_and_keeps_history(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("真实文件内容", encoding="utf-8")
    call = ToolCall(
        id="call-1",
        name="read_file",
        input=json.dumps({"path": str(target)}),
    )
    provider = FakeProvider(
        [
            [
                StreamEvent(text="我先读取。"),
                StreamEvent(tool_calls=[call]),
                StreamEvent(usage=Usage(12, 3)),
                StreamEvent(done=True),
            ],
            [
                StreamEvent(text="文件已读取"),
                StreamEvent(usage=Usage(20, 4)),
                StreamEvent(done=True),
            ],
        ]
    )
    conversation = Conversation()
    conversation.add_user("读取文件")

    events = [
        event
        async for event in Agent(
            provider, new_default_registry(), "test", permission_engine(tmp_path)
        ).run(conversation, Mode.DEFAULT, asyncio.Event())
    ]

    assert [event.iter for event in events if event.iter] == [1, 2]
    assert [event.tool.phase for event in events if event.tool] == [Phase.START, Phase.END]
    assert [event.usage.input for event in events if event.usage] == [12, 20]
    assert "我先读取。文件已读取" == "".join(event.text for event in events)
    assert events[-1].done
    assert provider.call_count == 2
    assert [message.role for message in provider.histories[1]] == ["user", "assistant", "tool"]
    assert [message.role for message in conversation.messages()] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert "真实文件内容" in conversation.messages()[2].tool_results[0].content
    assert conversation.messages()[-1].content == "文件已读取"


@pytest.mark.asyncio
async def test_agent_stops_at_iteration_limit() -> None:
    provider = FakeProvider([tool_event("repeat")], repeat_last=True)
    conversation = Conversation()
    conversation.add_user("不断调用")

    events = [
        event
        async for event in Agent(provider, registry_with_probe(), "test", permission_engine()).run(
            conversation, Mode.BYPASS, asyncio.Event()
        )
    ]

    assert provider.call_count == MAX_ITERATIONS
    assert [event.iter for event in events if event.iter] == list(range(1, MAX_ITERATIONS + 1))
    assert any(event.notice == NOTICE_MAX_ITER for event in events)
    assert events[-1].done
    assert conversation.last_role() == "assistant"


@pytest.mark.asyncio
async def test_agent_stops_after_consecutive_unknown_tools() -> None:
    provider = FakeProvider(
        [tool_event(f"unknown-{index}", "missing") for index in range(MAX_UNKNOWN_RUN)]
    )
    conversation = Conversation()
    conversation.add_user("调用未知工具")

    events = [
        event
        async for event in Agent(provider, Registry(), "test", permission_engine()).run(
            conversation, Mode.BYPASS, asyncio.Event()
        )
    ]

    assert provider.call_count == MAX_UNKNOWN_RUN
    assert any(event.notice == NOTICE_UNKNOWN_TOOLS for event in events)
    assert conversation.last_role() == "assistant"


@pytest.mark.asyncio
async def test_known_tool_resets_unknown_counter() -> None:
    scripts = [
        tool_event("unknown-1", "missing"),
        tool_event("unknown-2", "missing"),
        tool_event("known", "probe"),
        tool_event("unknown-3", "missing"),
        tool_event("unknown-4", "missing"),
        tool_event("unknown-5", "missing"),
    ]
    provider = FakeProvider(scripts)
    conversation = Conversation()
    conversation.add_user("重置计数")

    events = [
        event
        async for event in Agent(provider, registry_with_probe(), "test", permission_engine()).run(
            conversation, Mode.BYPASS, asyncio.Event()
        )
    ]

    assert provider.call_count == 6
    assert any(event.notice == NOTICE_UNKNOWN_TOOLS for event in events)


@dataclass
class ConcurrencyTracker:
    active_reads: int = 0
    peak_reads: int = 0
    read_ends: list[float] = field(default_factory=list)
    write_start: float = 0.0


class TimedTool:
    def __init__(self, name: str, read_only: bool, tracker: ConcurrencyTracker) -> None:
        self._name = name
        self.read_only = read_only
        self.tracker = tracker

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return "测试并发分批"

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"label": {"type": "string"}}}

    async def execute(self, args: str) -> Result:
        label = json.loads(args)["label"]
        loop = asyncio.get_running_loop()
        if self.read_only:
            self.tracker.active_reads += 1
            self.tracker.peak_reads = max(self.tracker.peak_reads, self.tracker.active_reads)
            await asyncio.sleep(0.03)
            self.tracker.active_reads -= 1
            self.tracker.read_ends.append(loop.time())
        else:
            self.tracker.write_start = loop.time()
        return Result(content=f"{self._name}-{label}")


@pytest.mark.asyncio
async def test_read_only_batch_is_concurrent_and_side_effect_follows() -> None:
    tracker = ConcurrencyTracker()
    registry = Registry()
    registry.register(TimedTool("ro", True, tracker))
    registry.register(TimedTool("rw", False, tracker))
    calls = [
        ToolCall("ro-1", "ro", '{"label":"a"}'),
        ToolCall("ro-2", "ro", '{"label":"b"}'),
        ToolCall("rw-1", "rw", '{"label":"c"}'),
    ]
    provider = FakeProvider(
        [
            [StreamEvent(tool_calls=calls), StreamEvent(done=True)],
            [StreamEvent(text="完成"), StreamEvent(done=True)],
        ]
    )
    conversation = Conversation()
    conversation.add_user("并发执行")

    events = [
        event
        async for event in Agent(provider, registry, "test", permission_engine()).run(
            conversation, Mode.BYPASS, asyncio.Event()
        )
    ]

    assert tracker.peak_reads >= 2
    assert tracker.write_start >= max(tracker.read_ends)
    starts = [event.tool.name for event in events if event.tool and event.tool.phase is Phase.START]
    ends = [event.tool.name for event in events if event.tool and event.tool.phase is Phase.END]
    assert starts == ["ro", "ro", "rw"]
    assert ends == ["ro", "ro", "rw"]
    assert [result.content for result in conversation.messages()[2].tool_results] == [
        "ro-a",
        "ro-b",
        "rw-c",
    ]


class BlockingTool(ProbeTool):
    read_only = False

    async def execute(self, args: str) -> Result:
        await asyncio.sleep(10)
        return Result("不应完成")


@pytest.mark.asyncio
async def test_cancellation_completes_history_and_allows_next_turn() -> None:
    registry = Registry()
    registry.register(BlockingTool())
    provider = FakeProvider(
        [
            tool_event("blocking"),
            [StreamEvent(text="取消后继续成功"), StreamEvent(done=True)],
        ]
    )
    conversation = Conversation()
    conversation.add_user("开始阻塞工具")
    cancel = asyncio.Event()
    events = []

    async for event in Agent(provider, registry, "test", permission_engine()).run(
        conversation, Mode.BYPASS, cancel
    ):
        events.append(event)
        if event.tool and event.tool.phase is Phase.START:
            cancel.set()

    assert [message.role for message in conversation.messages()] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert conversation.messages()[2].tool_results[0].is_error
    assert conversation.messages()[2].tool_results[0].content == NOTICE_CANCELLED
    assert conversation.messages()[-1].content == NOTICE_CANCELLED

    conversation.add_user("继续")
    resumed = [
        event
        async for event in Agent(provider, registry, "test", permission_engine()).run(
            conversation, Mode.BYPASS, asyncio.Event()
        )
    ]
    assert any(event.text == "取消后继续成功" for event in resumed)
    assert resumed[-1].done


@pytest.mark.asyncio
async def test_stream_error_emits_error_and_keeps_history_valid() -> None:
    failure = RuntimeError("模拟流错误")
    provider = FakeProvider([[StreamEvent(err=failure)]])
    conversation = Conversation()
    conversation.add_user("触发错误")

    events = [
        event
        async for event in Agent(provider, Registry(), "test", permission_engine()).run(
            conversation, Mode.DEFAULT, asyncio.Event()
        )
    ]

    assert any(event.err is failure for event in events)
    assert conversation.last_role() == "assistant"
    assert conversation.messages()[-1].content == NOTICE_STREAM_ERR


@pytest.mark.asyncio
async def test_plan_mode_only_exposes_read_only_tools() -> None:
    provider = FakeProvider([[StreamEvent(text="计划完成"), StreamEvent(done=True)]])
    conversation = Conversation()
    conversation.add_user("制定计划")

    events = [
        event
        async for event in Agent(provider, new_default_registry(), "test", permission_engine()).run(
            conversation, Mode.PLAN, asyncio.Event()
        )
    ]

    assert [definition.name for definition in provider.tool_definitions[0]] == [
        "read_file",
        "glob",
        "grep",
    ]
    request = provider.requests[0]
    assert request.system.stable
    assert request.system.environment
    assert request.reminder == prompt.plan_reminder(True)
    assert "<system-reminder>" in request.reminder
    assert events[-1].done


@pytest.mark.asyncio
async def test_plan_reminder_frequency_and_history_is_not_polluted() -> None:
    scripts = [tool_event(f"call-{index}") for index in range(4)]
    scripts.append([StreamEvent(text="计划完成"), StreamEvent(done=True)])
    provider = FakeProvider(scripts)
    conversation = Conversation()
    conversation.add_user("制定多轮计划")

    events = [
        event
        async for event in Agent(provider, registry_with_probe(), "test", permission_engine()).run(
            conversation, Mode.PLAN, asyncio.Event()
        )
    ]

    assert PLAN_REMINDER_INTERVAL == 4
    assert provider.requests[0].reminder == prompt.plan_reminder(True)
    assert all(
        request.reminder == prompt.plan_reminder(False) for request in provider.requests[1:4]
    )
    assert provider.requests[4].reminder == prompt.plan_reminder(True)
    assert len({request.system.stable for request in provider.requests}) == 1
    assert not any("<system-reminder>" in message.content for message in conversation.messages())
    assert events[-1].done


@pytest.mark.asyncio
async def test_normal_and_plan_modes_share_stable_system_and_usage_cache_fields() -> None:
    normal_provider = FakeProvider(
        [[StreamEvent(usage=Usage(10, 2, cache_write=7, cache_read=3)), StreamEvent(done=True)]]
    )
    normal_conversation = Conversation()
    normal_conversation.add_user("普通模式")
    normal_events = [
        event
        async for event in Agent(
            normal_provider, new_default_registry(), "test", permission_engine()
        ).run(normal_conversation, Mode.DEFAULT, asyncio.Event())
    ]
    plan_provider = FakeProvider([[StreamEvent(text="计划"), StreamEvent(done=True)]])
    plan_conversation = Conversation()
    plan_conversation.add_user("规划模式")
    _ = [
        event
        async for event in Agent(
            plan_provider, new_default_registry(), "test", permission_engine()
        ).run(plan_conversation, Mode.PLAN, asyncio.Event())
    ]

    assert normal_provider.requests[0].system.stable == plan_provider.requests[0].system.stable
    assert normal_provider.requests[0].reminder == ""
    assert [definition.name for definition in normal_provider.requests[0].tools] == [
        "read_file",
        "write_file",
        "edit_file",
        "bash",
        "glob",
        "grep",
    ]
    usage = next(event.usage for event in normal_events if event.usage is not None)
    assert (usage.input, usage.output, usage.cache_write, usage.cache_read) == (10, 2, 7, 3)


@pytest.mark.asyncio
async def test_denied_and_allowed_read_results_keep_order_and_loop_continues(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    inside = root / "inside.txt"
    outside = tmp_path / "outside.txt"
    inside.write_text("inside", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")
    calls = [
        ToolCall("denied", "read_file", json.dumps({"path": str(outside)})),
        ToolCall("allowed", "read_file", json.dumps({"path": str(inside)})),
    ]
    provider = FakeProvider(
        [
            [StreamEvent(tool_calls=calls), StreamEvent(done=True)],
            [StreamEvent(text="已根据结果继续"), StreamEvent(done=True)],
        ]
    )
    conversation = Conversation()
    conversation.add_user("读取两个文件")

    outputs = [
        output
        async for output in Agent(
            provider, new_default_registry(), "test", permission_engine(root)
        ).run(conversation, Mode.DEFAULT, asyncio.Event())
    ]

    results = conversation.messages()[2].tool_results
    assert [(result.tool_call_id, result.is_error) for result in results] == [
        ("denied", True),
        ("allowed", False),
    ]
    assert "项目目录之外" in results[0].content
    assert "inside" in results[1].content
    assert not any(isinstance(output, ApprovalRequest) for output in outputs)
    assert provider.call_count == 2
    assert conversation.messages()[-1].content == "已根据结果继续"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("outcome", "executed", "persisted"),
    [
        (Outcome.ALLOW_ONCE, True, False),
        (Outcome.ALLOW_FOREVER, True, True),
        (Outcome.DENY_ONCE, False, False),
    ],
)
async def test_approval_three_choices(
    tmp_path: Path,
    outcome: Outcome,
    executed: bool,
    persisted: bool,
) -> None:
    target = tmp_path / f"choice-{outcome.name}.txt"
    call = ToolCall(
        "write",
        "write_file",
        json.dumps({"path": str(target), "content": "approved"}),
    )
    provider = FakeProvider(
        [
            [StreamEvent(tool_calls=[call]), StreamEvent(done=True)],
            [StreamEvent(text="审批后继续"), StreamEvent(done=True)],
        ]
    )
    engine = permission_engine(tmp_path)
    conversation = Conversation()
    conversation.add_user("写文件")
    approvals: list[ApprovalRequest] = []

    async for output in Agent(provider, new_default_registry(), "test", engine).run(
        conversation, Mode.DEFAULT, asyncio.Event()
    ):
        if isinstance(output, ApprovalRequest):
            approvals.append(output)
            output.respond.set_result(outcome)

    assert len(approvals) == 1
    assert "需确认" in approvals[0].reason
    assert target.exists() is executed
    result = conversation.messages()[2].tool_results[0]
    assert result.is_error is (not executed)
    assert provider.call_count == 2
    assert Path(engine.local_path).exists() is persisted
    if persisted:
        content = Path(engine.local_path).read_text(encoding="utf-8")
        assert "Write(choice-ALLOW_FOREVER.txt)" in content
        reloaded, error = new_engine(str(tmp_path))
        assert error is None
        assert reloaded.check(Mode.DEFAULT, call, False)[0] is Decision.ALLOW


@pytest.mark.asyncio
async def test_cancelling_task_while_waiting_for_approval_cleans_up(
    tmp_path: Path,
) -> None:
    target = tmp_path / "cancelled.txt"
    call = ToolCall(
        "write",
        "write_file",
        json.dumps({"path": str(target), "content": "must not exist"}),
    )
    provider = FakeProvider([[StreamEvent(tool_calls=[call]), StreamEvent(done=True)]])
    conversation = Conversation()
    conversation.add_user("等待审批")
    cancel = asyncio.Event()
    approval_seen = asyncio.Event()
    approval: ApprovalRequest | None = None
    current = asyncio.current_task()
    baseline = {task for task in asyncio.all_tasks() if task is not current}

    async def collect() -> None:
        nonlocal approval
        async for output in Agent(
            provider, new_default_registry(), "test", permission_engine(tmp_path)
        ).run(conversation, Mode.DEFAULT, cancel):
            if isinstance(output, ApprovalRequest):
                approval = output
                approval_seen.set()

    task = asyncio.create_task(collect())
    await asyncio.wait_for(approval_seen.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1)
    await asyncio.sleep(0)

    assert approval is not None and approval.respond.cancelled()
    assert not target.exists()
    assert [message.role for message in conversation.messages()] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]
    assert conversation.messages()[2].tool_results[0].content == NOTICE_CANCELLED
    remaining = {
        pending
        for pending in asyncio.all_tasks()
        if pending is not asyncio.current_task() and not pending.done()
    }
    assert remaining <= baseline
