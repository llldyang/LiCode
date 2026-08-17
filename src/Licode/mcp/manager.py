"""MCP server 并发连接、工具缓存与生命周期管理。"""

import asyncio
import importlib
import os
import sys
from contextlib import AbstractAsyncContextManager, AsyncExitStack
from dataclasses import dataclass
from typing import Any, cast

import mcp.types as mtypes
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import Config, ServerConfig
from .tool import CallerSession, McpTool, adapt_tool

connect_timeout: float = 30.0
close_timeout: float = 5.0

_http_module = importlib.import_module("mcp.client.streamable_http")
_legacy_http_client = getattr(_http_module, "streamablehttp_client", None)
streamablehttp_client = _legacy_http_client or getattr(_http_module, "streamable_http_client")
_uses_httpx2 = _legacy_http_client is None


@dataclass
class _Session:
    name: str
    session: ClientSession


class Manager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: list[_Session] = []
        self._tools: list[McpTool] = []
        self._tasks: list[asyncio.Task[None]] = []
        self._close_requested = asyncio.Event()
        self._closed = False

    def tools(self) -> list[McpTool]:
        return list(self._tools)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._close_requested.set()
        if not self._tasks:
            return
        _, pending = await asyncio.wait(self._tasks, timeout=close_timeout)
        if pending:
            print(
                f"[mcp] warn: close timeout ({close_timeout}s), some sessions may leak",
                file=sys.stderr,
            )
            for task in pending:
                task.cancel()
            await asyncio.sleep(0)


async def new_manager(config: Config, version: str) -> Manager:
    manager = Manager()
    loop = asyncio.get_running_loop()
    ready: list[asyncio.Future[None]] = []
    for name, server in config.servers.items():
        signal: asyncio.Future[None] = loop.create_future()
        ready.append(signal)
        manager._tasks.append(
            asyncio.create_task(_connect_one(manager, name, server, version, signal))
        )
    if ready:
        await asyncio.gather(*ready)
    manager._tools.sort(key=lambda tool: tool.full_name)
    return manager


async def _close_stack(stack: AsyncExitStack, name: str) -> None:
    try:
        await stack.aclose()
    except Exception as exc:
        print(f"[mcp] warn: close server {name} failed: {exc}", file=sys.stderr)


async def _connect_one(
    manager: Manager,
    name: str,
    server: ServerConfig,
    version: str,
    ready: asyncio.Future[None],
) -> None:
    stack = AsyncExitStack()
    await stack.__aenter__()
    connected = False
    try:
        try:
            async with asyncio.timeout(connect_timeout):
                await _do_connect(manager, stack, name, server, version)
            connected = True
        except TimeoutError:
            print(
                f"[mcp] warn: connect server {name} timeout after {connect_timeout}s",
                file=sys.stderr,
            )
        except Exception as exc:
            print(f"[mcp] warn: connect server {name} failed: {exc}", file=sys.stderr)
        finally:
            if not ready.done():
                ready.set_result(None)

        if connected:
            await manager._close_requested.wait()
    finally:
        await _close_stack(stack, name)


async def _http_context(
    stack: AsyncExitStack, server: ServerConfig
) -> AbstractAsyncContextManager[Any]:
    if not _uses_httpx2:
        return cast(
            AbstractAsyncContextManager[Any],
            streamablehttp_client(server.url, headers=server.headers or None),
        )

    httpx2 = importlib.import_module("httpx2")
    client = httpx2.AsyncClient(headers=server.headers or None)
    await stack.enter_async_context(client)
    return cast(
        AbstractAsyncContextManager[Any],
        streamablehttp_client(server.url, http_client=client),
    )


async def _do_connect(
    manager: Manager,
    stack: AsyncExitStack,
    name: str,
    server: ServerConfig,
    version: str,
) -> None:
    if server.type == "stdio":
        parameters = StdioServerParameters(
            command=server.command,
            args=server.args,
            env={**os.environ, **server.env},
        )
        context: AbstractAsyncContextManager[Any] = cast(
            AbstractAsyncContextManager[Any], stdio_client(parameters)
        )
    else:
        context = await _http_context(stack, server)

    transport = await stack.enter_async_context(context)
    read, write = transport[0], transport[1]
    session = await stack.enter_async_context(
        ClientSession(
            read,
            write,
            client_info=mtypes.Implementation(name="Licode", version=version),
        )
    )
    await session.initialize()
    listed = await session.list_tools()

    by_name: dict[str, McpTool] = {}
    caller = cast(CallerSession, session)
    for remote in listed.tools:
        adapted = adapt_tool(name, remote, caller)
        if adapted is None:
            continue
        if adapted.full_name in by_name:
            print(
                f"[mcp] warn: duplicate tool {adapted.full_name}, keeping later definition",
                file=sys.stderr,
            )
        by_name[adapted.full_name] = adapted
    adapted_tools = list(by_name.values())

    async with manager._lock:
        manager._sessions.append(_Session(name, session))
        manager._tools.extend(adapted_tools)
    print(f"[mcp] connected server {name}: {len(adapted_tools)} tools", file=sys.stderr)
