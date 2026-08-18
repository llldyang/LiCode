"""斜杠命令注册、解析与内置命令。"""

from .builtins import register_builtins
from .command import Command, Handler, Kind
from .dispatch import parse
from .registry import Registry
from .skills import register_skills_as_commands, remove_skill_commands
from .ui import UI, NopUI

__all__ = [
    "Command",
    "Handler",
    "Kind",
    "NopUI",
    "Registry",
    "UI",
    "parse",
    "register_builtins",
    "register_skills_as_commands",
    "remove_skill_commands",
]
