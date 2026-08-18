"""历史会话列表扫描。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from Licode.compact import parse_session_time


@dataclass(frozen=True)
class SessionInfo:
    id: str
    title: str
    modified_at: datetime
    model: str
    size: int
    dir: str


def list_sessions(sessions_dir: str) -> list[SessionInfo]:
    root = Path(sessions_dir)
    if not root.is_dir():
        return []
    sessions: list[SessionInfo] = []
    for directory in root.iterdir():
        if not directory.is_dir():
            continue
        try:
            parse_session_time(directory.name)
        except ValueError:
            continue
        path = directory / "conversation.jsonl"
        if not path.is_file():
            continue
        title = "(无标题)"
        model = ""
        try:
            with path.open(encoding="utf-8") as file:
                for line in file:
                    try:
                        entry = json.loads(line)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if not model and isinstance(entry.get("model"), str):
                        model = entry["model"]
                    if entry.get("role") == "user":
                        content = str(entry.get("content", ""))
                        title = content if len(content) <= 50 else content[:49] + "…"
                        break
            stat = path.stat()
        except OSError:
            continue
        sessions.append(
            SessionInfo(
                id=directory.name,
                title=title,
                modified_at=datetime.fromtimestamp(stat.st_mtime),
                model=model,
                size=stat.st_size,
                dir=str(directory.resolve()),
            )
        )
    return sorted(sessions, key=lambda item: item.modified_at, reverse=True)
