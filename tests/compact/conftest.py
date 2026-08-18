from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    ManageInput,
    RecoveryState,
    SessionContext,
    TriggerKind,
)
from Licode.conversation import Conversation
from Licode.llm import Request, StreamEvent, ToolDefinition


def summary_text(label: str = "摘要") -> str:
    sections = "\n".join(
        [
            "## 1 主要请求和意图",
            "## 2 关键技术概念",
            "## 3 文件和代码段",
            "## 4 错误和修复",
            "## 5 问题解决过程",
            "## 6 所有用户消息原文",
            "## 7 待办任务",
            "## 8 当前工作（最详细）",
            "## 9 可能的下一步",
        ]
    )
    return f"<analysis>草稿</analysis><summary>{label}\n{sections}</summary>"


class FakeCompactProvider:
    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.requests: list[Request] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        script = self.scripts[len(self.requests) - 1]
        for event in script:
            yield event


def make_input(
    tmp_path: Path,
    provider: FakeCompactProvider,
    conversation: Conversation,
    *,
    trigger: TriggerKind = TriggerKind.AUTO,
    estimated: int = 0,
    context_window: int = 200000,
    replacement: ContentReplacementState | None = None,
    recovery: RecoveryState | None = None,
    tracking: CompactCircuitBreaker | None = None,
    tool_defs: list[ToolDefinition] | None = None,
) -> ManageInput:
    spill_dir = tmp_path / "tool-results"
    spill_dir.mkdir(exist_ok=True)
    return ManageInput(
        conv=conversation,
        provider=provider,
        context_window=context_window,
        tool_defs=tool_defs or [],
        replacement=replacement or ContentReplacementState(),
        recovery=recovery or RecoveryState(),
        auto_tracking=tracking or CompactCircuitBreaker(),
        session=SessionContext("test-session", str(tmp_path), str(spill_dir)),
        usage_anchor=0,
        anchor_msg_len=0,
        estimated_token=estimated,
        trigger=trigger,
    )
