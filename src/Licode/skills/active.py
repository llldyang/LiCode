"""跨 Agent 轮次保存已激活 Skill。"""

import threading
from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ActiveEntry:
    name: str
    body: str


class ActiveSkills:
    def __init__(self) -> None:
        self._entries: list[ActiveEntry] = []
        self._index: dict[str, int] = {}
        self._lock = threading.RLock()

    def activate(self, name: str, body: str) -> None:
        with self._lock:
            index = self._index.get(name)
            entry = ActiveEntry(name=name, body=body)
            if index is None:
                self._index[name] = len(self._entries)
                self._entries.append(entry)
            else:
                self._entries[index] = entry

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._index.clear()

    def snapshot(self) -> list[ActiveEntry]:
        with self._lock:
            return list(self._entries)

    def names(self) -> list[str]:
        with self._lock:
            return [entry.name for entry in self._entries]


_current_active: ContextVar[ActiveSkills | None] = ContextVar(
    "Licode_current_active_skills", default=None
)


def bind_active_skills(active: ActiveSkills) -> Token[ActiveSkills | None]:
    return _current_active.set(active)


def reset_active_skills(token: Token[ActiveSkills | None]) -> None:
    _current_active.reset(token)


def current_active_skills(default: ActiveSkills) -> ActiveSkills:
    return _current_active.get() or default
