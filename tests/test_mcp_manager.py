import asyncio
import os
import time
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
from typing import Any

import mcp.types as mtypes
import pytest

from Licode.mcp import Config, ServerConfig
from Licode.mcp import manager as manager_module
from Licode.mcp.manager import new_manager
from Licode.mcp.tool import McpTool


class EmptyCaller:
    async def call_tool(self, name, arguments):
        return mtypes.CallToolResult(content=[])


def local_tool(name: str) -> McpTool:
    return McpTool(name, "remote", "description", {"type": "object"}, False, EmptyCaller())


@pytest.mark.asyncio
async def test_empty_manager_closes_immediately() -> None:
    manager = await new_manager(Config(), "test")

    assert manager.tools() == []
    assert manager.tools() is not manager.tools()
    await manager.close()
    await manager.close()


@pytest.mark.asyncio
async def test_connection_failure_isolated_and_tools_sorted(monkeypatch, capsys) -> None:
    original = manager_module._do_connect

    async def mixed_connect(manager, stack, name, server, version):
        if name != "good":
            return await original(manager, stack, name, server, version)
        async with manager._lock:
            manager._tools.extend([local_tool("mcp__good__z"), local_tool("mcp__good__a")])

    monkeypatch.setattr(manager_module, "_do_connect", mixed_connect)
    config = Config(
        {
            "broken": ServerConfig(type="stdio", command="Z:/no/such/mcp-server.exe"),
            "good": ServerConfig(type="stdio", command="unused"),
        }
    )

    manager = await new_manager(config, "test")

    assert [tool.full_name for tool in manager.tools()] == ["mcp__good__a", "mcp__good__z"]
    assert "connect server broken failed" in capsys.readouterr().err
    await manager.close()


@pytest.mark.asyncio
async def test_connection_timeout_is_bounded(monkeypatch, capsys) -> None:
    async def blocked(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(manager_module, "_do_connect", blocked)
    monkeypatch.setattr(manager_module, "connect_timeout", 0.02)
    started = time.monotonic()

    manager = await new_manager(
        Config({"slow": ServerConfig(type="stdio", command="unused")}), "test"
    )

    assert time.monotonic() - started < 0.5
    assert "connect server slow timeout" in capsys.readouterr().err
    await manager.close()


@pytest.mark.asyncio
async def test_close_timeout_is_bounded(monkeypatch, capsys) -> None:
    class BlockingContext:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *args):
            await asyncio.Event().wait()

    async def connect_with_blocking_close(manager, stack, name, server, version):
        await stack.enter_async_context(BlockingContext())

    monkeypatch.setattr(manager_module, "_do_connect", connect_with_blocking_close)
    monkeypatch.setattr(manager_module, "close_timeout", 0.02)
    manager = await new_manager(
        Config({"slow-close": ServerConfig(type="stdio", command="unused")}), "test"
    )
    started = time.monotonic()

    await manager.close()
    await asyncio.sleep(0)

    assert time.monotonic() - started < 0.5
    assert "close timeout" in capsys.readouterr().err
    assert all(task.done() for task in manager._tasks)


@pytest.mark.asyncio
async def test_stdio_connect_initializes_lists_and_adapts(monkeypatch, capsys) -> None:
    captured: dict[str, Any] = {}

    class TransportContext(AbstractAsyncContextManager):
        async def __aenter__(self):
            return (object(), object())

        async def __aexit__(self, *args):
            return None

    def fake_stdio(parameters):
        captured["parameters"] = parameters
        return TransportContext()

    class FakeSession(AbstractAsyncContextManager):
        def __init__(self, read, write, client_info):
            captured["client_info"] = client_info
            self.initialized = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def initialize(self):
            self.initialized = True

        async def list_tools(self):
            assert self.initialized
            return SimpleNamespace(
                tools=[
                    mtypes.Tool(name="echo", inputSchema={"type": "object"}),
                    mtypes.Tool(name="echo", description="later", inputSchema={}),
                    mtypes.Tool(name="bad.name", inputSchema={}),
                ]
            )

    monkeypatch.setattr(manager_module, "stdio_client", fake_stdio)
    monkeypatch.setattr(manager_module, "ClientSession", FakeSession)

    manager = await new_manager(
        Config(
            {
                "demo": ServerConfig(
                    type="stdio",
                    command="python",
                    args=["server.py"],
                    env={"MCP_TEST_ENV": "injected"},
                )
            }
        ),
        "1.2.3",
    )

    assert [tool.full_name for tool in manager.tools()] == ["mcp__demo__echo"]
    assert manager.tools()[0].description() == "later"
    assert captured["parameters"].env["MCP_TEST_ENV"] == "injected"
    assert captured["parameters"].env["PATH"] == os.environ["PATH"]
    assert captured["client_info"].version == "1.2.3"
    error = capsys.readouterr().err
    assert "duplicate tool" in error
    assert "skip tool mcp__demo__bad.name" in error
    assert "connected server demo: 1 tools" in error
    await manager.close()
