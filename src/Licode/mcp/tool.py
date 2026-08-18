"""把 MCP 远端工具适配为 LiCode 工具协议。"""

import asyncio
import json
import re
import sys
from dataclasses import dataclass
from typing import Any, Protocol

import mcp.types as mtypes

from Licode.tool import Result

call_timeout: float = 30.0
_VALID_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
_non_text_warn_once: set[str] = set()


class CallerSession(Protocol):
    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None
    ) -> mtypes.CallToolResult: ...


@dataclass
class McpTool:
    full_name: str
    remote_name: str
    _description: str
    _parameters: dict[str, Any]
    read_only: bool
    caller: CallerSession
    is_system = False

    def name(self) -> str:
        return self.full_name

    def description(self) -> str:
        return self._description

    def parameters(self) -> dict[str, Any]:
        return dict(self._parameters)

    async def execute(self, args: str | dict[str, Any] | None) -> Result:
        """把 LiCode 的 JSON 参数转换后调用远端工具。"""

        if isinstance(args, str):
            try:
                parsed: Any = json.loads(args)
            except (json.JSONDecodeError, TypeError) as exc:
                return Result(content=f"MCP 工具参数解析失败: {exc}", is_error=True)
        else:
            parsed = args
        if parsed is not None and not isinstance(parsed, dict):
            return Result(content="MCP 工具参数必须是 JSON 对象", is_error=True)
        arguments = parsed or None

        try:
            result = await asyncio.wait_for(
                self.caller.call_tool(self.remote_name, arguments),
                timeout=call_timeout,
            )
        except TimeoutError:
            return Result(content="MCP 工具调用超时 (30s)", is_error=True)
        except Exception as exc:
            return Result(content=f"MCP 工具调用失败: {exc}", is_error=True)

        texts: list[str] = []
        dropped = False
        for block in result.content:
            if isinstance(block, mtypes.TextContent):
                texts.append(block.text)
            else:
                dropped = True
        if dropped and self.full_name not in _non_text_warn_once:
            _non_text_warn_once.add(self.full_name)
            print(
                f"[mcp] warn: tool {self.full_name} returned non-text content blocks (dropped)",
                file=sys.stderr,
            )
        is_error = getattr(result, "isError", getattr(result, "is_error", False))
        return Result(content="\n".join(texts), is_error=bool(is_error))


def adapt_tool(server_name: str, tool: mtypes.Tool, session: CallerSession) -> McpTool | None:
    full_name = f"mcp__{server_name}__{tool.name}"
    if _VALID_NAME.fullmatch(full_name) is None:
        print(
            f"[mcp] warn: skip tool {full_name}: name contains illegal characters",
            file=sys.stderr,
        )
        return None
    description = tool.description or f"来自 MCP server {server_name} 的工具 {tool.name}"
    raw_schema = getattr(tool, "inputSchema", getattr(tool, "input_schema", None))
    schema = dict(raw_schema) if raw_schema else {"type": "object"}
    annotations = getattr(tool, "annotations", None)
    read_only_hint = (
        getattr(annotations, "readOnlyHint", getattr(annotations, "read_only_hint", None))
        if annotations is not None
        else None
    )
    read_only = read_only_hint is True
    return McpTool(
        full_name=full_name,
        remote_name=tool.name,
        _description=description,
        _parameters=schema,
        read_only=read_only,
        caller=session,
    )
