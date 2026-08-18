"""Hook 规则、条件与动作数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from Licode.permission.matcher import Matcher

from .event import Event


class CombineMode(StrEnum):
    ALL_OF = "all_of"
    ANY_OF = "any_of"


class ActionType(StrEnum):
    SHELL = "shell"
    PROMPT = "prompt"
    HTTP = "http"
    SUBAGENT = "subagent"


@dataclass(frozen=True)
class AtomCondition:
    field: str
    matcher: Matcher


@dataclass(frozen=True)
class Condition:
    mode: CombineMode
    atoms: list[AtomCondition]


@dataclass(frozen=True)
class ShellAction:
    command: str


@dataclass(frozen=True)
class PromptAction:
    text: str


@dataclass(frozen=True)
class HttpAction:
    url: str
    method: str = "POST"
    headers: dict[str, str] = field(default_factory=dict)
    body: str | None = None


@dataclass(frozen=True)
class SubagentAction:
    agent_name: str
    prompt: str


@dataclass(frozen=True)
class Action:
    type: ActionType
    shell: ShellAction | None = None
    prompt: PromptAction | None = None
    http: HttpAction | None = None
    subagent: SubagentAction | None = None


@dataclass(frozen=True)
class Rule:
    name: str
    event: Event
    action: Action
    condition: Condition | None = None
    only_once: bool = False
    asyncio_mode: bool = False
    timeout_s: float = 30.0
    source: str = ""


Payload = dict[str, Any]
