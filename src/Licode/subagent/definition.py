"""SubAgent 角色的数据定义。"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Literal

from Licode.permission import Mode


class Source(IntEnum):
    """角色定义来源，数值越大优先级越高。"""

    BUILTIN = 0
    USER = 1
    PROJECT = 2
    PLUGIN = 3

    def __str__(self) -> str:
        return {
            Source.BUILTIN: "builtin",
            Source.USER: "user",
            Source.PROJECT: "project",
            Source.PLUGIN: "plugin",
        }.get(self, "unknown")


BUILTIN = Source.BUILTIN
USER = Source.USER
PROJECT = Source.PROJECT
PLUGIN = Source.PLUGIN


@dataclass
class Definition:
    """一个由 Markdown 和 YAML frontmatter 描述的完整 Agent 角色。"""

    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    model: Literal["haiku", "sonnet", "opus", "inherit"] = "inherit"
    max_turns: int = 0
    permission_mode: Mode = Mode.DEFAULT
    dont_ask: bool = False
    background: bool = False
    isolation: str = ""
    system_prompt: str = ""
    file_path: str = ""
    source: Source = Source.BUILTIN

    def is_fork(self) -> bool:
        """是否为继承父对话的临时 Fork 定义。"""

        return self.name == "__fork__"
