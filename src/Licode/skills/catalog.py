"""Skill 的两级目录扫描、覆盖与热重载。"""

from __future__ import annotations

import logging
import threading
from builtins import list as builtin_list
from pathlib import Path
from typing import TYPE_CHECKING

from .adapter import to_prompt_items
from .parser import SkillParseError, parse_skill_dir, parse_skill_file
from .types import Skill, SkillSource, SkillSummary, ValidationIssue

if TYPE_CHECKING:
    from Licode.prompt import SkillCatalogItem
    from Licode.tool import Registry

logger = logging.getLogger(__name__)

PROJECT_SKILLS_DIR = ".Licode/skills"
USER_SKILLS_DIR = "~/.Licode/skills"


class Catalog:
    def __init__(self, work_dir: Path) -> None:
        self._work_dir = work_dir.resolve()
        self._project_dir = self._work_dir / PROJECT_SKILLS_DIR
        self._user_dir = Path(USER_SKILLS_DIR).expanduser()
        self._by_name: dict[str, Skill] = {}
        self._cache: dict[str, Skill] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()

    @classmethod
    def load(cls, work_dir: Path | str) -> Catalog:
        catalog = cls(Path(work_dir))
        catalog.reload()
        return catalog

    def reload(self, work_dir: Path | str | None = None) -> tuple[set[str], set[str]]:
        if work_dir is not None:
            self._work_dir = Path(work_dir).resolve()
            self._project_dir = self._work_dir / PROJECT_SKILLS_DIR

        loaded: dict[str, Skill] = {}
        for directory, source in (
            (self._user_dir, SkillSource.USER),
            (self._project_dir, SkillSource.PROJECT),
        ):
            for skill in self._scan_directory(directory, source):
                loaded[skill.name] = skill

        with self._lock:
            before = set(self._by_name)
            self._by_name = loaded
            self._cache = dict(loaded)
            self._order = sorted(loaded)
        return set(loaded) - before, before - set(loaded)

    def _scan_directory(self, path: Path, source: SkillSource) -> list[Skill]:
        if not path.is_dir():
            return []
        skills: list[Skill] = []
        try:
            entries = sorted(path.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            logger.warning("Skipping %s skills directory '%s': %s", source.value, path, exc)
            return []
        for entry in entries:
            try:
                if entry.is_dir() and (entry / "SKILL.md").is_file():
                    skills.append(parse_skill_dir(entry, source))
                elif entry.is_file() and entry.suffix.lower() == ".md":
                    skills.append(parse_skill_file(entry, source, is_directory=False))
            except SkillParseError as exc:
                logger.warning("Skipping %s skill '%s': %s", source.value, entry.stem, exc)
        return skills

    def get(self, name: str) -> Skill | None:
        with self._lock:
            skill = self._by_name.get(name)
            fallback = self._cache.get(name)
        if skill is None:
            return None
        try:
            refreshed = parse_skill_file(
                skill.source_path,
                skill.source,
                is_directory=skill.is_directory,
            )
            if refreshed.name != name:
                raise SkillParseError(f"热重载后的名称从 {name} 变为 {refreshed.name}")
        except SkillParseError as exc:
            logger.warning(
                "Reloading %s skill '%s' failed, using cache: %s",
                skill.source.value,
                name,
                exc,
            )
            return fallback
        with self._lock:
            self._by_name[name] = refreshed
            self._cache[name] = refreshed
        return refreshed

    def list(self) -> builtin_list[Skill]:
        with self._lock:
            return [self._by_name[name] for name in self._order]

    def names(self) -> builtin_list[str]:
        with self._lock:
            return list(self._order)

    def summaries(self) -> builtin_list[SkillSummary]:
        return [
            SkillSummary(skill.name, skill.description, skill.source.value, skill.mode)
            for skill in self.list()
        ]

    def get_source_label(self, name: str) -> str:
        skill = self.get(name)
        return skill.source.value if skill is not None else ""

    def validate_tools(self, registry: Registry) -> builtin_list[ValidationIssue]:
        return [
            ValidationIssue(skill.name, tool_name)
            for skill in self.list()
            for tool_name in skill.allowed_tools
            if registry.get(tool_name) is None
        ]

    def remove(self, name: str) -> None:
        with self._lock:
            self._by_name.pop(name, None)
            self._cache.pop(name, None)
            self._order = sorted(self._by_name)

    def to_prompt_items(self) -> builtin_list[SkillCatalogItem]:
        return to_prompt_items(self.list())
