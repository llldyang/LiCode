"""工具抽象、注册中心与默认工具集。"""

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

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

    @property
    def read_only(self) -> bool: ...

    @property
    def is_system(self) -> bool: ...

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


# 注册中心反向引用上述基础类型，因此在这些类型定义后导入。
from .ctx import cwd_from_ctx, resolve_path, with_cwd  # noqa: E402
from .registry import Registry  # noqa: E402


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
    "cwd_from_ctx",
    "InstallSkillTool",
    "LoadSkillTool",
    "new_default_registry",
    "resolve_path",
    "with_cwd",
]


def __getattr__(name: str) -> object:
    if name == "LoadSkillTool":
        from .load_skill import LoadSkillTool

        return LoadSkillTool
    if name == "InstallSkillTool":
        from .install_skill import InstallSkillTool

        return InstallSkillTool
    raise AttributeError(name)
