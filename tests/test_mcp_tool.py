from typing import Any

import mcp.types as mtypes
import pytest

from Licode.mcp import tool as mcp_tool
from Licode.mcp.tool import McpTool, adapt_tool


class StubSession:
    def __init__(self, result: mtypes.CallToolResult | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    async def call_tool(self, name: str, arguments: dict[str, Any] | None) -> mtypes.CallToolResult:
        self.calls.append((name, arguments))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


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
    invalid = adapt_tool("bad.server", remote_tool(), session)

    assert isinstance(adapted, McpTool)
    assert adapted.name() == "mcp__demo__echo"
    assert "来自 MCP server demo" in adapted.description()
    assert adapted.parameters() == {"type": "object", "required": ["text"]}
    assert adapted.read_only is False
    assert isinstance(readonly, McpTool) and readonly.read_only is True
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
