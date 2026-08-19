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
    CompactPhase,
    Phase,
    SessionRuntime,
)
from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from Licode.conversation import Conversation
from Licode.llm import (
    Message,
    PromptTooLongError,
    Request,
    StreamEvent,
    ToolCall,
    ToolDefinition,
    ToolResult,
    Usage,
)
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


class FixedResultTool:
    read_only = True

    def __init__(self, content: str) -> None:
        self.content = content

    def name(self) -> str:
        return "fixed_result"

    def description(self) -> str:
        return "返回固定测试内容"

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: str) -> Result:
        del args
        return Result(content=self.content)


class FakeMemoryManager:
    def __init__(self) -> None:
        self.calls: list[list[Message]] = []
        self.updated = asyncio.Event()

    def load_index(self) -> str:
        return "长期记忆索引"

    async def update_async(self, messages: list[Message]) -> None:
        self.calls.append(messages)
        self.updated.set()


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


def session_runtime(tmp_path: Path, context_window: int = 200000) -> SessionRuntime:
    return SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(str(tmp_path)),
        context_window=context_window,
    )


def compact_summary() -> str:
    return (
        "<analysis>草稿</analysis><summary>"
        + "\n".join(f"## {index} 小节" for index in range(1, 10))
        + "</summary>"
    )


@pytest.mark.asyncio
async def test_agent_injects_context_and_explicit_memory_signal(tmp_path: Path) -> None:
    provider = FakeProvider([[StreamEvent(text="已记住"), StreamEvent(done=True)]])
    memory_manager = FakeMemoryManager()
    agent = Agent(
        provider,
        Registry(),
        "test",
        permission_engine(tmp_path),
        runtime=session_runtime(tmp_path),
        memory_manager=memory_manager,  # type: ignore[arg-type]
        instruction_text="项目指令内容",
        memory_text="启动记忆",
    )
    conversation = Conversation()
    conversation.add_user("请记住使用中文")

    async for _ in agent.run(conversation, Mode.DEFAULT, asyncio.Event()):
        pass
    await asyncio.wait_for(memory_manager.updated.wait(), timeout=1)

    assert provider.call_count == 1
    assert "项目指令内容" in provider.requests[0].system.stable
    assert "长期记忆索引" in provider.requests[0].system.stable
    assert [message.content for message in memory_manager.calls[0]] == [
        "请记住使用中文",
        "已记住",
    ]


@pytest.mark.asyncio
async def test_agent_updates_memory_every_five_turns(tmp_path: Path) -> None:
    provider = FakeProvider(
        [[StreamEvent(text=f"回答 {index}"), StreamEvent(done=True)] for index in range(5)]
    )
    memory_manager = FakeMemoryManager()
    agent = Agent(
        provider,
        Registry(),
        "test",
        permission_engine(tmp_path),
        runtime=session_runtime(tmp_path),
        memory_manager=memory_manager,  # type: ignore[arg-type]
    )
    conversation = Conversation()

    for index in range(5):
        conversation.add_user(f"问题 {index}")
        async for _ in agent.run(conversation, Mode.DEFAULT, asyncio.Event()):
            pass
    await asyncio.wait_for(memory_manager.updated.wait(), timeout=1)

    assert agent.runtime.turn_count == 5
    assert len(memory_manager.calls) == 1
    assert memory_manager.calls[0][0].content == "问题 4"


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


class DangerousBashProbe(ProbeTool):
    """记录危险命令是否越过权限引擎到达执行层。"""

    read_only = False

    def __init__(self) -> None:
        self.executed = False

    def name(self) -> str:
        return "bash"

    async def execute(self, args: str) -> Result:
        self.executed = True
        return Result("危险命令不应执行")


@pytest.mark.asyncio
async def test_blacklisted_command_is_backfilled_without_execution_in_bypass() -> None:
    tool = DangerousBashProbe()
    registry = Registry()
    registry.register(tool)
    call = ToolCall("danger", "bash", json.dumps({"command": "rm -rf /"}))
    provider = FakeProvider(
        [
            [StreamEvent(tool_calls=[call]), StreamEvent(done=True)],
            [StreamEvent(text="已停止危险操作"), StreamEvent(done=True)],
        ]
    )
    conversation = Conversation()
    conversation.add_user("执行危险命令")

    outputs = [
        output
        async for output in Agent(provider, registry, "test", permission_engine()).run(
            conversation, Mode.BYPASS, asyncio.Event()
        )
    ]

    result = conversation.messages()[2].tool_results[0]
    assert not tool.executed
    assert result.tool_call_id == "danger"
    assert result.is_error and "危险命令黑名单" in result.content
    assert provider.call_count == 2
    assert conversation.messages()[-1].content == "已停止危险操作"
    assert not any(isinstance(output, ApprovalRequest) for output in outputs)


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


@pytest.mark.asyncio
async def test_agent_emits_auto_compact_events(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            [
                StreamEvent(text=compact_summary()),
                StreamEvent(usage=Usage(900, 99)),
                StreamEvent(done=True),
            ],
            [
                StreamEvent(text="压缩后继续"),
                StreamEvent(usage=Usage(100, 10)),
                StreamEvent(done=True),
            ],
        ]
    )
    conversation = Conversation()
    for _ in range(10):
        conversation.add_user("u" * 7000)
        conversation.add_assistant("a" * 7000)
    runtime = session_runtime(tmp_path, context_window=60000)

    events = [
        event
        async for event in Agent(
            provider,
            new_default_registry(),
            "test",
            permission_engine(tmp_path),
            runtime=runtime,
        ).run(conversation, Mode.DEFAULT, asyncio.Event())
    ]

    compact_events = [event.compact for event in events if event.compact is not None]
    assert [event.phase for event in compact_events] == [
        CompactPhase.BEFORE_AUTO,
        CompactPhase.AFTER_AUTO,
    ]
    assert compact_events[1].before > compact_events[1].after
    assert provider.requests[0].tools is None
    assert provider.requests[1].tools is provider.tool_definitions[1]
    recovery_text = provider.requests[1].messages[0].content
    assert "## 当前可用工具" in recovery_text
    for definition in provider.requests[1].tools or []:
        assert f"- {definition.name}:" in recovery_text
        schema = json.dumps(
            definition.input_schema,
            separators=(",", ":"),
            ensure_ascii=False,
            sort_keys=True,
        )
        assert f"input_schema: {schema}" in recovery_text
    assert runtime.usage_anchor == 110


@pytest.mark.asyncio
async def test_agent_has_no_compact_event_below_threshold(tmp_path: Path) -> None:
    provider = FakeProvider([[StreamEvent(text="完成"), StreamEvent(done=True)]])
    conversation = Conversation()
    conversation.add_user("短请求")
    runtime = session_runtime(tmp_path)
    events = [
        event
        async for event in Agent(
            provider,
            Registry(),
            "test",
            permission_engine(tmp_path),
            runtime=runtime,
        ).run(conversation, Mode.DEFAULT, asyncio.Event())
    ]
    assert not any(event.compact is not None for event in events)


@pytest.mark.asyncio
async def test_layer1_reduction_does_not_emit_layer2_events(tmp_path: Path) -> None:
    provider = FakeProvider([[StreamEvent(text="完成"), StreamEvent(done=True)]])
    conversation = Conversation()
    conversation.replace_history(
        [Message(role="tool", tool_results=[ToolResult("large", "x" * 240000)])]
    )
    events = [
        event
        async for event in Agent(
            provider,
            Registry(),
            "test",
            permission_engine(tmp_path),
            runtime=session_runtime(tmp_path, context_window=100000),
        ).run(conversation, Mode.DEFAULT, asyncio.Event())
    ]

    assert provider.call_count == 1
    assert not any(event.compact is not None for event in events)
    assert "[content offloaded]" in provider.requests[0].messages[0].tool_results[0].content


@pytest.mark.asyncio
async def test_agent_offloads_80kb_result_before_next_request(tmp_path: Path) -> None:
    content = "x" * 80000
    call = ToolCall("large-result", "fixed_result", "{}")
    provider = FakeProvider(
        [
            [StreamEvent(tool_calls=[call]), StreamEvent(done=True)],
            [StreamEvent(text="完成"), StreamEvent(done=True)],
        ]
    )
    registry = Registry()
    registry.register(FixedResultTool(content))
    runtime = session_runtime(tmp_path)
    conversation = Conversation()
    conversation.add_user("读取大结果")

    events = [
        event
        async for event in Agent(
            provider,
            registry,
            "test",
            permission_engine(tmp_path),
            runtime=runtime,
        ).run(conversation, Mode.BYPASS, asyncio.Event())
    ]

    assert events[-1].done
    preview = provider.requests[1].messages[-1].tool_results[0].content
    spill_path = Path(runtime.session.spill_dir) / call.id
    assert "original size: 80000" in preview
    assert "[saved to]" in preview and str(spill_path) in preview
    assert "[head preview]" in preview
    assert "文件读取工具" in preview and "不要凭头部预览猜测" in preview
    assert spill_path.stat().st_size == 80000


@pytest.mark.asyncio
async def test_agent_completes_30_turn_long_session_with_compaction(tmp_path: Path) -> None:
    class LongSessionProvider:
        def __init__(self) -> None:
            self.main_calls = 0
            self.summary_calls = 0

        @property
        def name(self) -> str:
            return "long-session"

        @property
        def model(self) -> str:
            return "long-session-model"

        async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
            if request.tools is None:
                self.summary_calls += 1
                yield StreamEvent(text=compact_summary())
                yield StreamEvent(done=True)
                return
            self.main_calls += 1
            yield StreamEvent(
                tool_calls=[ToolCall(f"long-{self.main_calls}", "fixed_result", "{}")]
            )
            yield StreamEvent(done=True)

    provider = LongSessionProvider()
    registry = Registry()
    registry.register(FixedResultTool("r" * 30000))
    conversation = Conversation()
    conversation.add_user("连续执行三十轮")
    events = [
        event
        async for event in Agent(
            provider,
            registry,
            "test",
            permission_engine(tmp_path),
            runtime=session_runtime(tmp_path, context_window=50000),
            max_turns=30,
        ).run(conversation, Mode.BYPASS, asyncio.Event())
    ]

    assert events[-1].done
    assert provider.main_calls == 30
    assert provider.summary_calls >= 1
    assert conversation.length() < 15


@pytest.mark.asyncio
async def test_compacted_request_restores_latest_files_and_exact_tools(tmp_path: Path) -> None:
    summary = compact_summary().replace("</summary>", "\n原始请求一\n原始请求二</summary>")
    provider = FakeProvider(
        [
            [StreamEvent(text=summary), StreamEvent(done=True)],
            [StreamEvent(text="恢复后完成"), StreamEvent(done=True)],
        ]
    )
    runtime = session_runtime(tmp_path, context_window=60000)
    paths = [tmp_path / f"file-{index}.txt" for index in range(7)]
    for index, path in enumerate(paths):
        runtime.recovery.record_file(str(path), f"content-{index}")
        await asyncio.sleep(0.001)

    conversation = Conversation()
    conversation.add_user("原始请求一")
    conversation.add_assistant("x" * 140000)
    conversation.add_user("原始请求二")
    conversation.add_assistant("y" * 140000)
    registry = new_default_registry()
    events = [
        event
        async for event in Agent(
            provider,
            registry,
            "test",
            permission_engine(tmp_path),
            runtime=runtime,
        ).run(conversation, Mode.DEFAULT, asyncio.Event())
    ]

    assert events[-1].done
    recovery_text = provider.requests[1].messages[0].content
    assert "原始请求一" in recovery_text and "原始请求二" in recovery_text
    expected_paths = [str(path.resolve()) for path in reversed(paths[2:])]
    assert all(path in recovery_text for path in expected_paths)
    assert str(paths[0].resolve()) not in recovery_text
    assert str(paths[1].resolve()) not in recovery_text
    assert [recovery_text.index(path) for path in expected_paths] == sorted(
        recovery_text.index(path) for path in expected_paths
    )

    definitions = provider.requests[1].tools or []
    tool_block = recovery_text.split("## 当前可用工具\n", 1)[1].split("\n\n## 边界提示", 1)[0]
    assert tool_block.count("input_schema:") == len(definitions)
    assert {definition.name for definition in definitions} == {
        line.split(":", 1)[0][2:] for line in tool_block.splitlines() if line.startswith("- ")
    }
    for definition in definitions:
        schema = json.dumps(
            definition.input_schema,
            separators=(",", ":"),
            ensure_ascii=False,
            sort_keys=True,
        )
        assert f"- {definition.name}:" in tool_block
        assert f"input_schema: {schema}" in tool_block
    assert "需要文件原文、错误原文或用户原话时" in recovery_text


@pytest.mark.asyncio
async def test_agent_emergency_compact_retries_once(tmp_path: Path) -> None:
    ptl = PromptTooLongError("主请求过长")
    provider = FakeProvider(
        [
            [StreamEvent(err=ptl)],
            [StreamEvent(text=compact_summary()), StreamEvent(done=True)],
            [StreamEvent(text="重试成功"), StreamEvent(usage=Usage(50, 5)), StreamEvent(done=True)],
        ]
    )
    conversation = Conversation()
    conversation.add_user("继续任务")
    runtime = session_runtime(tmp_path)
    events = [
        event
        async for event in Agent(
            provider,
            Registry(),
            "test",
            permission_engine(tmp_path),
            runtime=runtime,
        ).run(conversation, Mode.DEFAULT, asyncio.Event())
    ]

    compact_events = [event.compact for event in events if event.compact is not None]
    assert [event.phase for event in compact_events] == [
        CompactPhase.BEFORE_EMERGENCY,
        CompactPhase.AFTER_EMERGENCY,
    ]
    assert provider.call_count == 3
    assert events[-1].done
    assert conversation.messages()[-1].content == "重试成功"


@pytest.mark.asyncio
async def test_agent_second_prompt_too_long_is_not_retried(tmp_path: Path) -> None:
    ptl = PromptTooLongError("主请求过长")
    provider = FakeProvider(
        [
            [StreamEvent(err=ptl)],
            [StreamEvent(text=compact_summary()), StreamEvent(done=True)],
            [StreamEvent(err=ptl)],
        ]
    )
    conversation = Conversation()
    conversation.add_user("继续任务")
    events = [
        event
        async for event in Agent(
            provider,
            Registry(),
            "test",
            permission_engine(tmp_path),
            runtime=session_runtime(tmp_path),
        ).run(conversation, Mode.DEFAULT, asyncio.Event())
    ]
    assert provider.call_count == 3
    assert any(event.err is ptl for event in events)
    assert not events[-1].done


@pytest.mark.asyncio
async def test_agent_does_not_retry_when_emergency_output_is_still_too_large(
    tmp_path: Path,
) -> None:
    ptl = PromptTooLongError("主请求过长")
    oversized_summary = "<summary>" + "摘" * 50000 + "</summary>"
    provider = FakeProvider(
        [
            [StreamEvent(err=ptl)],
            [StreamEvent(text=oversized_summary), StreamEvent(done=True)],
        ]
    )
    runtime = session_runtime(tmp_path, context_window=34000)
    runtime.usage_anchor = 99
    runtime.anchor_msg_len = 1
    conversation = Conversation()
    conversation.add_user("继续任务")
    events = [
        event
        async for event in Agent(
            provider,
            Registry(),
            "test",
            permission_engine(tmp_path),
            runtime=runtime,
        ).run(conversation, Mode.DEFAULT, asyncio.Event())
    ]

    assert provider.call_count == 2
    assert any(event.err is ptl for event in events)
    assert runtime.usage_anchor == 0
    assert runtime.anchor_msg_len == 0


@pytest.mark.asyncio
async def test_agent_records_clean_read_file_snapshot(tmp_path: Path) -> None:
    target = tmp_path / "raw.txt"
    target.write_text("第一行\n第二行", encoding="utf-8")
    call = ToolCall("read", "read_file", json.dumps({"path": str(target)}))
    provider = FakeProvider(
        [
            [StreamEvent(tool_calls=[call]), StreamEvent(done=True)],
            [StreamEvent(text="完成"), StreamEvent(done=True)],
        ]
    )
    runtime = session_runtime(tmp_path)
    conversation = Conversation()
    conversation.add_user("读取")
    _ = [
        event
        async for event in Agent(
            provider,
            new_default_registry(),
            "test",
            permission_engine(tmp_path),
            runtime=runtime,
        ).run(conversation, Mode.DEFAULT, asyncio.Event())
    ]
    record = runtime.recovery.snapshot()[0]
    assert record.path == str(target.resolve())
    assert record.content == target.read_bytes().decode("utf-8")
    assert "\t" not in record.content


@pytest.mark.asyncio
async def test_run_force_compact_waits_for_active_run(tmp_path: Path) -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class BlockingProvider:
        @property
        def name(self) -> str:
            return "blocking"

        @property
        def model(self) -> str:
            return "blocking"

        async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
            if request.tools is None:
                yield StreamEvent(text=compact_summary())
                return
            started.set()
            await release.wait()
            yield StreamEvent(text="完成")
            yield StreamEvent(done=True)

    conversation = Conversation()
    conversation.add_user("运行")
    agent = Agent(
        BlockingProvider(),
        Registry(),
        "test",
        permission_engine(tmp_path),
        runtime=session_runtime(tmp_path),
    )

    async def collect() -> None:
        _ = [event async for event in agent.run(conversation, Mode.DEFAULT, asyncio.Event())]

    run_task = asyncio.create_task(collect())
    await asyncio.wait_for(started.wait(), timeout=1)
    compact_task = asyncio.create_task(agent.run_force_compact(conversation, []))
    await asyncio.sleep(0)
    assert not compact_task.done()
    release.set()
    await asyncio.wait_for(run_task, timeout=1)
    before, after = await asyncio.wait_for(compact_task, timeout=1)
    assert before >= 0
    assert after >= 0


@pytest.mark.asyncio
async def test_usage_anchor_is_replaced_across_runs(tmp_path: Path) -> None:
    provider = FakeProvider(
        [
            [StreamEvent(text="一"), StreamEvent(usage=Usage(900, 100))],
            [StreamEvent(text="二"), StreamEvent(usage=Usage(1200, 200, cache_read=100))],
            [StreamEvent(text="三"), StreamEvent(usage=Usage(1800, 200, cache_write=200))],
        ]
    )
    runtime = session_runtime(tmp_path)
    agent = Agent(
        provider,
        Registry(),
        "test",
        permission_engine(tmp_path),
        runtime=runtime,
    )
    conversation = Conversation()
    observed: list[int] = []
    for text in ("第一轮", "第二轮", "第三轮"):
        conversation.add_user(text)
        _ = [event async for event in agent.run(conversation, Mode.DEFAULT, asyncio.Event())]
        observed.append(runtime.usage_anchor)
    assert observed == [1000, 1500, 2200]


@pytest.mark.asyncio
async def test_agent_reuses_same_tool_definition_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import Licode.agent as agent_module

    original = agent_module.manage_context
    definition_ids: list[int] = []

    async def capture(manage_input):
        definition_ids.append(id(manage_input.tool_defs))
        return await original(manage_input)

    monkeypatch.setattr(agent_module, "manage_context", capture)
    provider = FakeProvider([[StreamEvent(text="完成"), StreamEvent(done=True)]])
    conversation = Conversation()
    conversation.add_user("检查工具定义")
    _ = [
        event
        async for event in Agent(
            provider,
            new_default_registry(),
            "test",
            permission_engine(tmp_path),
            runtime=session_runtime(tmp_path),
        ).run(conversation, Mode.DEFAULT, asyncio.Event())
    ]
    assert definition_ids == [id(provider.requests[0].tools)]
