"""Skill 的元数据与来源类型。"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Literal

SkillMode = Literal["inline", "fork"]
ForkContext = Literal["none", "recent", "full"]


class SkillSource(Enum):
    USER = "user"
    PROJECT = "project"


@dataclass(frozen=True, slots=True)
class SkillMeta:
    name: str
    description: str
    allowed_tools: list[str] = field(default_factory=list)
    mode: SkillMode = "inline"
    fork_context: ForkContext = "none"
    model: str | None = None

    def is_fork(self) -> bool:
        return self.mode == "fork"


@dataclass(frozen=True, slots=True)
class Skill:
    meta: SkillMeta
    prompt_body: str
    source_dir: Path
    source_path: Path
    source: SkillSource
    is_directory: bool

    @property
    def name(self) -> str:
        return self.meta.name

    @property
    def description(self) -> str:
        return self.meta.description

    @property
    def allowed_tools(self) -> list[str]:
        return list(self.meta.allowed_tools)

    @property
    def mode(self) -> SkillMode:
        return self.meta.mode

    @property
    def context(self) -> ForkContext:
        return self.meta.fork_context

    @property
    def model(self) -> str | None:
        return self.meta.model


# spec 使用 SkillDef 名称；实现统一由 Skill 承载。
SkillDef = Skill


@dataclass(frozen=True, slots=True)
class SkillSummary:
    name: str
    description: str
    source: str
    mode: str


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    skill_name: str
    tool_name: str
