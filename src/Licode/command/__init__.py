"""斜杠命令注册、解析与内置命令。"""

from .builtins import register_builtins
from .command import ArgsHandler, Command, Handler, Kind
from .dispatch import parse, parse_with_args
from .registry import Registry
from .skills import register_skills_as_commands, remove_skill_commands
from .ui import UI, NopUI, WorktreeAccessor, WorktreeSummary

__all__ = [
    "ArgsHandler",
    "Command",
    "Handler",
    "Kind",
    "NopUI",
    "Registry",
    "UI",
    "WorktreeAccessor",
    "WorktreeSummary",
    "parse",
    "parse_with_args",
    "register_builtins",
    "register_skills_as_commands",
    "remove_skill_commands",
]
