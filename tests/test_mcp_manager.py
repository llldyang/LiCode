import asyncio
import ctypes
import os
import sys
import time
from contextlib import AbstractAsyncContextManager
from types import SimpleNamespace
from typing import Any

import mcp.types as mtypes
import pytest
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from Licode.mcp import Config, ServerConfig
from Licode.mcp import manager as manager_module
from Licode.mcp.manager import new_manager
from Licode.mcp.tool import McpTool


class EmptyCaller:
    async def call_tool(self, name, arguments):
        return mtypes.CallToolResult(content=[])


def local_tool(name: str) -> McpTool:
    return McpTool(name, "remote", "description", {"type": "object"}, False, EmptyCaller())


def process_is_running(pid: int) -> bool:
    """跨平台检查测试子进程，Windows 下不发送可能终止进程的信号。"""

    if os.name == "nt":
        process_query_limited_information = 0x1000
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


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


@pytest.mark.asyncio
async def test_real_stdio_server_handshake_call_env_and_shutdown(tmp_path) -> None:
    server_script = tmp_path / "stdio_server.py"
    server_script.write_text(
        "from mcp.server import MCPServer\n"
        "import os\n"
        "server = MCPServer('stdio-test')\n"
        "@server.tool()\n"
        "def inspect_env(text: str) -> str:\n"
        "    return f\"{os.environ.get('MCP_TEST_ENV')}|{text}|{os.getpid()}\"\n"
        "server.run()\n",
        encoding="utf-8",
    )
    manager = await new_manager(
        Config(
            {
                "stdio": ServerConfig(
                    type="stdio",
                    command=sys.executable,
                    args=[str(server_script)],
                    env={"MCP_TEST_ENV": "injected"},
                )
            }
        ),
        "test",
    )

    try:
        [tool] = manager.tools()
        result = await tool.execute('{"text": "hello"}')
        injected, text, raw_pid = result.content.split("|")
        pid = int(raw_pid)
        assert (tool.full_name, injected, text, result.is_error) == (
            "mcp__stdio__inspect_env",
            "injected",
            "hello",
            False,
        )
        assert process_is_running(pid)
    finally:
        await manager.close()

    deadline = time.monotonic() + 3
    while process_is_running(pid) and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    assert not process_is_running(pid)
    assert all(task.done() for task in manager._tasks)


@pytest.mark.asyncio
async def test_real_http_server_receives_headers_on_every_request(monkeypatch) -> None:
    import httpx2

    server = MCPServer("http-test")

    @server.tool()
    def echo(text: str) -> str:
        return text

    app = server.streamable_http_app(
        json_response=True,
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    received_headers: list[dict[bytes, bytes]] = []

    async def capture_headers(scope, receive, send):
        if scope["type"] == "http":
            received_headers.append(dict(scope["headers"]))
        await app(scope, receive, send)

    original_client = httpx2.AsyncClient

    def asgi_client(*args, **kwargs):
        # 保留生产代码设置的默认 headers，只把网络传输替换为进程内 ASGI。
        kwargs["transport"] = httpx2.ASGITransport(app=capture_headers)
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", asgi_client)
    async with app.router.lifespan_context(app):
        manager = await new_manager(
            Config(
                {
                    "http": ServerConfig(
                        type="http",
                        url="http://127.0.0.1/mcp",
                        headers={"Authorization": "Bearer test-token"},
                    )
                }
            ),
            "test",
        )
        try:
            [tool] = manager.tools()
            result = await tool.execute('{"text": "hello"}')
            assert tool.full_name == "mcp__http__echo"
            assert result.content == "hello"
            assert result.is_error is False
        finally:
            await manager.close()

    assert received_headers
    assert all(headers[b"authorization"] == b"Bearer test-token" for headers in received_headers)
