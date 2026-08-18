"""按内置、用户、项目优先级加载 SubAgent 角色。"""

from __future__ import annotations

import builtins
import sys
import threading
from pathlib import Path

from Licode.permission import Mode

from .definition import Definition, Source
from .embed import builtin_definitions
from .parser import parse_file


class Catalog:
    """线程安全地保存角色定义和来源视图。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._defs: dict[str, Definition] = {}
        self._by_source: dict[Source, list[Definition]] = {}

    def _add_all(self, definitions: list[Definition], source: Source) -> None:
        with self._lock:
            self._by_source.setdefault(source, []).extend(definitions)
            for definition in definitions:
                self._defs[definition.name] = definition

    def resolve(self, name: str) -> Definition | None:
        with self._lock:
            return self._defs.get(name)

    def list(self) -> list[Definition]:
        with self._lock:
            return sorted(self._defs.values(), key=lambda item: item.name)

    def list_by_source(self, source: Source) -> builtins.list[Definition]:
        with self._lock:
            return list(self._by_source.get(source, []))

    def fork_definition(self) -> Definition:
        return Definition(
            name="__fork__",
            description="Fork-based subagent",
            model="inherit",
            max_turns=25,
            permission_mode=Mode.DEFAULT,
        )


def _load_from_dir(directory: Path, source: Source) -> list[Definition]:
    if not directory.is_dir():
        return []
    result: list[Definition] = []
    for path in sorted(directory.glob("*.md")):
        try:
            result.append(parse_file(str(path), source))
        except Exception as exc:
            print(f"跳过 Agent 定义 {path}: {exc}", file=sys.stderr)
    return result


def load_catalog(root: str) -> Catalog:
    """顺序加载内置、用户与项目定义，后加载的同名角色覆盖前者。"""

    catalog = Catalog()
    catalog._add_all(builtin_definitions(), Source.BUILTIN)
    catalog._add_all(
        _load_from_dir(Path.home() / ".Licode" / "agents", Source.USER),
        Source.USER,
    )
    catalog._add_all(
        _load_from_dir(Path(root) / ".Licode" / "agents", Source.PROJECT),
        Source.PROJECT,
    )
    return catalog
