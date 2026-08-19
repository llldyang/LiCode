import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import mcp.types as mtypes
import pytest

from Licode.agent import Agent, ApprovalRequest
from Licode.conversation import Conversation
from Licode.llm import Request, StreamEvent, ToolCall
from Licode.mcp import tool as mcp_tool
from Licode.mcp.tool import McpTool, adapt_tool
from Licode.permission import Decision, Engine, Mode
from Licode.permission.rule import Rule, RuleSet
from Licode.tool import Registry, new_default_registry


class StubSession:
    def __init__(self, result: mtypes.CallToolResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any] | None) -> mtypes.CallToolResult:
        self.calls.append((name, arguments))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class ScriptProvider:
    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.call_count = 0

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        script = self.scripts[self.call_count]
        self.call_count += 1
        for event in script:
            yield event


def remote_tool(
    *,
    name: str = "echo",
    description: str | None = "Echo text",
    schema: dict[str, Any] | None = None,
    read_only: bool | None = None,
) -> mtypes.Tool:
    annotations = mtypes.ToolAnnotations(readOnlyHint=read_only) if read_only is not None else None
    return mtypes.Tool(
        name=name,
        description=description,
        inputSchema=schema if schema is not None else {},
        annotations=annotations,
    )


def text_result(*texts: str, is_error: bool = False) -> mtypes.CallToolResult:
    return mtypes.CallToolResult(
        content=[mtypes.TextContent(text=text) for text in texts],
        isError=is_error,
    )


def test_adapt_tool_names_fields_schema_and_read_only(capsys) -> None:
    session = StubSession(text_result("ok"))
    adapted = adapt_tool(
        "demo",
        remote_tool(description=None, schema={"type": "object", "required": ["text"]}),
        session,
    )
    readonly = adapt_tool("demo", remote_tool(name="list", read_only=True), session)
    writable = adapt_tool("demo", remote_tool(name="change", read_only=False), session)
    invalid = adapt_tool("bad.server", remote_tool(), session)

    assert isinstance(adapted, McpTool)
    assert adapted.name() == "mcp__demo__echo"
    assert "来自 MCP server demo" in adapted.description()
    assert adapted.parameters() == {"type": "object", "required": ["text"]}
    assert adapted.read_only is False
    assert isinstance(readonly, McpTool) and readonly.read_only is True
    assert isinstance(writable, McpTool) and writable.read_only is False
    assert readonly.parameters() == {"type": "object"}
    assert invalid is None
    assert "name contains illegal characters" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_execute_joins_text_and_maps_remote_error() -> None:
    session = StubSession(text_result("first", "second", is_error=True))
    adapted = adapt_tool("demo", remote_tool(), session)
    assert adapted is not None

    result = await adapted.execute('{"text": "hello"}')

    assert result.content == "first\nsecond"
    assert result.is_error is True
    assert session.calls == [("echo", {"text": "hello"})]


@pytest.mark.asyncio
async def test_execute_turns_protocol_and_argument_errors_into_results() -> None:
    session = StubSession(RuntimeError("connection lost"))
    adapted = adapt_tool("demo", remote_tool(), session)
    assert adapted is not None

    failed = await adapted.execute({})
    malformed = await adapted.execute("not-json")

    assert failed.is_error and "MCP 工具调用失败: connection lost" in failed.content
    assert malformed.is_error and "MCP 工具参数解析失败" in malformed.content
    assert session.calls == [("echo", None)]


@pytest.mark.asyncio
async def test_execute_timeout_returns_error(monkeypatch) -> None:
    class BlockingSession:
        async def call_tool(self, name, arguments):
            await __import__("asyncio").Event().wait()
            raise AssertionError("unreachable")

    monkeypatch.setattr(mcp_tool, "call_timeout", 0.02)
    adapted = adapt_tool("demo", remote_tool(), BlockingSession())
    assert adapted is not None

    result = await adapted.execute(None)

    assert result.is_error and "超时" in result.content


@pytest.mark.asyncio
async def test_non_text_blocks_are_dropped_and_warn_once(capsys) -> None:
    mcp_tool._non_text_warn_once.clear()
    result = mtypes.CallToolResult(
        content=[
            mtypes.TextContent(text="visible"),
            mtypes.ImageContent(data="AA==", mimeType="image/png"),
        ]
    )
    adapted = adapt_tool("demo", remote_tool(), StubSession(result))
    assert adapted is not None

    first = await adapted.execute(None)
    second = await adapted.execute(None)

    assert first.content == second.content == "visible"
    assert capsys.readouterr().err.count("returned non-text content blocks") == 1


def test_namespaces_do_not_collide_with_each_other_or_builtin_tools() -> None:
    session = StubSession(text_result("ok"))
    alpha = adapt_tool("alpha", remote_tool(), session)
    beta = adapt_tool("beta", remote_tool(), session)
    assert alpha is not None and beta is not None
    registry = new_default_registry()

    registry.register(alpha)
    registry.register(beta)

    names = [name for name, _ in registry.items()]
    assert len(names) == len(set(names)) == 8
    assert names[-2:] == ["mcp__alpha__echo", "mcp__beta__echo"]


def test_mcp_tools_reuse_existing_permission_rules_and_mode_fallback(tmp_path: Path) -> None:
    engine = Engine(
        root=str(tmp_path.resolve()),
        local_path=str(tmp_path / ".Licode" / "settings.local.yaml"),
    )
    read_call = ToolCall("read", "mcp__demo__inspect", '{"command": "rm -rf /"}')
    write_call = ToolCall("write", "mcp__demo__change", '{"path": "../outside"}')

    # 未知工具没有内置命令或文件目标，因此只进入规则与模式兜底。
    assert engine.check(Mode.DEFAULT, read_call, True)[0] is Decision.ALLOW
    assert engine.check(Mode.DEFAULT, write_call, False)[0] is Decision.ASK
    assert engine.check(Mode.BYPASS, write_call, False)[0] is Decision.ALLOW

    engine.local = RuleSet(allow=[Rule("mcp__demo__*", None, True)])
    assert engine.check(Mode.DEFAULT, write_call, False)[0] is Decision.ALLOW

    engine.local = RuleSet(deny=[Rule("mcp__demo__change", None, False)])
    decision, reason = engine.check(Mode.BYPASS, write_call, False)
    assert decision is Decision.DENY
    assert "匹配 deny 规则" in reason


@pytest.mark.asyncio
async def test_protocol_error_is_fed_back_and_agent_loop_continues(tmp_path: Path) -> None:
    adapted = adapt_tool(
        "demo",
        remote_tool(read_only=True),
        StubSession(RuntimeError("connection lost")),
    )
    assert adapted is not None
    registry = Registry()
    registry.register(adapted)
    provider = ScriptProvider(
        [
            [
                StreamEvent(
                    tool_calls=[ToolCall("mcp-call", adapted.full_name, '{"text": "hello"}')]
                ),
                StreamEvent(done=True),
            ],
            [StreamEvent(text="已收到错误并继续"), StreamEvent(done=True)],
        ]
    )
    conversation = Conversation()
    conversation.add_user("调用 MCP 工具")
    engine = Engine(
        root=str(tmp_path.resolve()),
        local_path=str(tmp_path / ".Licode" / "settings.local.yaml"),
    )

    outputs = [
        output
        async for output in Agent(provider, registry, "test", engine).run(
            conversation, Mode.DEFAULT, asyncio.Event()
        )
    ]

    result = conversation.messages()[2].tool_results[0]
    assert result.is_error is True
    assert "MCP 工具调用失败: connection lost" in result.content
    assert not any(isinstance(output, ApprovalRequest) for output in outputs)
    assert provider.call_count == 2
    assert conversation.messages()[-1].content == "已收到错误并继续"
