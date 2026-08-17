"""工具注册中心。"""

import asyncio

from Licode.llm import ToolDefinition

from . import DEFAULT_TIMEOUT, Result, Tool


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
        return [self._definition(name) for name in self._order]

    def read_only_definitions(self) -> list[ToolDefinition]:
        """只导出只读工具定义，并保持注册顺序。"""

        return [self._definition(name) for name in self._order if self._tools[name].read_only]

    def is_read_only(self, name: str) -> bool:
        tool = self.get(name)
        return tool is not None and tool.read_only

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

    def _definition(self, name: str) -> ToolDefinition:
        tool = self._tools[name]
        return ToolDefinition(
            name=name,
            description=tool.description(),
            input_schema=tool.parameters(),
        )
