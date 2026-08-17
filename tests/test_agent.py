import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from Licode.agent import Agent, Phase
from Licode.conversation import Conversation
from Licode.llm import Message, StreamEvent, ToolCall, ToolDefinition
from Licode.tool import new_default_registry


class FakeProvider:
    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.call_count = 0
        self.histories: list[list[Message]] = []
        self.tool_definitions: list[list[ToolDefinition]] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    async def stream(
        self, msgs: list[Message], tools: list[ToolDefinition]
    ) -> AsyncIterator[StreamEvent]:
        self.histories.append(msgs)
        self.tool_definitions.append(tools)
        script = self.scripts[self.call_count]
        self.call_count += 1
        for event in script:
            yield event


@pytest.mark.asyncio
async def test_agent_executes_tool_and_feeds_result_back(tmp_path: Path) -> None:
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
                StreamEvent(done=True),
            ],
            [StreamEvent(text="文件已读取"), StreamEvent(done=True)],
        ]
    )
    conversation = Conversation()
    conversation.add_user("读取文件")

    events = [event async for event in Agent(provider, new_default_registry()).run(conversation)]

    tool_events = [event.tool for event in events if event.tool is not None]
    assert [event.phase for event in tool_events] == [Phase.START, Phase.END]
    assert "真实文件内容" in tool_events[1].result
    assert "文件已读取" == "".join(event.text for event in events).removeprefix("我先读取。")
    assert provider.call_count == 2
    assert len(provider.tool_definitions[0]) == 6
    assert [message.role for message in provider.histories[1]] == ["user", "assistant", "tool"]
    assert conversation.messages()[-1].role == "assistant"
    assert conversation.messages()[-1].content == "文件已读取"


@pytest.mark.asyncio
async def test_agent_ignores_second_request_tool_calls(tmp_path: Path) -> None:
    target = tmp_path / "note.txt"
    target.write_text("内容", encoding="utf-8")
    first = ToolCall(
        id="call-1",
        name="read_file",
        input=json.dumps({"path": str(target)}),
    )
    second = ToolCall(id="call-2", name="write_file", input="{}")
    provider = FakeProvider(
        [
            [StreamEvent(tool_calls=[first]), StreamEvent(done=True)],
            [StreamEvent(tool_calls=[second]), StreamEvent(done=True)],
        ]
    )
    conversation = Conversation()
    conversation.add_user("需要两步工具")

    events = [event async for event in Agent(provider, new_default_registry()).run(conversation)]

    starts = [event for event in events if event.tool and event.tool.phase is Phase.START]
    assert len(starts) == 1
    assert starts[0].tool is not None and starts[0].tool.name == "read_file"
    assert provider.call_count == 2
    assert conversation.messages()[-1].content == "已达到本章的单轮工具调用上限。"
