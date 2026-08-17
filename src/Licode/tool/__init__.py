"""工具抽象、注册中心与默认工具集。"""

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from Licode.llm import ToolDefinition

DEFAULT_TIMEOUT: float = 30.0


@dataclass
class Result:
    """工具执行结果，失败也以值返回。"""

    content: str
    is_error: bool = False


@runtime_checkable
class Tool(Protocol):
    """所有内置工具遵循的统一接口。"""

    def name(self) -> str: ...

    def description(self) -> str: ...

    def parameters(self) -> dict[str, Any]: ...

    async def execute(self, args: str) -> Result: ...


def _truncate(value: str, max_lines: int, max_chars: int) -> str:
    """按行数和字符数截断文本，并明确标记。"""

    lines = value.splitlines()
    truncated = len(lines) > max_lines or len(value) > max_chars
    if not truncated:
        return value

    shortened = "\n".join(lines[:max_lines])
    marker = "\n[truncated]"
    shortened = shortened[: max(0, max_chars - len(marker))]
    return shortened.rstrip("\n") + marker


class Registry:
    """集中登记、查找、导出和执行工具。"""

    def __init__(self) -> None:
        self._order: list[str] = []
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        name = tool.name()
        if name in self._tools:
            raise ValueError(f"工具已注册: {name}")
        self._order.append(name)
        self._tools[name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def definitions(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name=name,
                description=self._tools[name].description(),
                input_schema=self._tools[name].parameters(),
            )
            for name in self._order
        ]

    async def execute(self, name: str, args: str, timeout: float = DEFAULT_TIMEOUT) -> Result:
        tool = self.get(name)
        if tool is None:
            return Result(content=f"未知工具: {name}", is_error=True)
        try:
            return await asyncio.wait_for(tool.execute(args), timeout=timeout)
        except TimeoutError:
            return Result(content=f"工具 {name} 执行超时（{timeout}s）", is_error=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return Result(content=f"工具 {name} 异常: {exc}", is_error=True)


def new_default_registry() -> Registry:
    """按固定顺序注册六个核心工具。"""

    from .bash import BashTool
    from .edit_file import EditFileTool
    from .glob_tool import GlobTool
    from .grep_tool import GrepTool
    from .read_file import ReadFileTool
    from .write_file import WriteFileTool

    registry = Registry()
    for tool in (
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        BashTool(),
        GlobTool(),
        GrepTool(),
    ):
        registry.register(tool)
    return registry


__all__ = [
    "DEFAULT_TIMEOUT",
    "Registry",
    "Result",
    "Tool",
    "new_default_registry",
]
