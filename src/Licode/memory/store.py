"""单级长期记忆的 Markdown 文件存储。"""

from __future__ import annotations

import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .types import NoteType, UpdateAction

SAFE_NAME_RE = re.compile(r"^[a-z0-9_]+\.md$")


class Store:
    def __init__(self, dir: str) -> None:
        self._dir = Path(dir).resolve()
        self._lock = threading.Lock()

    @property
    def dir(self) -> str:
        return str(self._dir)

    def ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def load_index(self) -> str:
        try:
            return (self._dir / "MEMORY.md").read_text(encoding="utf-8")
        except OSError:
            return ""

    def apply(self, actions: list[UpdateAction]) -> None:
        with self._lock:
            self.ensure_dir()
            for action in actions:
                if action.action == "create":
                    self._create(action)
                elif action.action == "update":
                    self._update(action)
                elif action.action == "delete":
                    self._delete(action)
            self._rebuild_index()

    def _create(self, action: UpdateAction) -> None:
        note_type = NoteType(action.type)
        slug = action.slug.strip().lower()
        filename = f"{note_type.value}_{slug}.md"
        path = self._safe_path(filename)
        now = datetime.now().astimezone().isoformat()
        self._write_note(path, note_type.value, action.title, action.content, now, now)

    def _update(self, action: UpdateAction) -> None:
        path = self._safe_path(action.filename)
        if not path.is_file():
            return
        metadata, _ = self._read_note(path)
        note_type = str(metadata.get("type", ""))
        title = action.title or str(metadata.get("title", ""))
        created = str(metadata.get("created", datetime.now().astimezone().isoformat()))
        updated = datetime.now().astimezone().isoformat()
        self._write_note(path, note_type, title, action.content, created, updated)

    def _delete(self, action: UpdateAction) -> None:
        path = self._safe_path(action.filename)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def _safe_path(self, filename: str) -> Path:
        if SAFE_NAME_RE.fullmatch(filename) is None or filename == "memory.md":
            raise ValueError(f"无效的记忆文件名: {filename}")
        return self._dir / filename

    @staticmethod
    def _write_note(
        path: Path,
        note_type: str,
        title: str,
        content: str,
        created: str,
        updated: str,
    ) -> None:
        frontmatter = yaml.safe_dump(
            {
                "type": note_type,
                "title": title,
                "created": created,
                "updated": updated,
            },
            allow_unicode=True,
            sort_keys=False,
        ).strip()
        path.write_text(f"---\n{frontmatter}\n---\n{content.rstrip()}\n", encoding="utf-8")

    @staticmethod
    def _read_note(path: Path) -> tuple[dict[str, Any], str]:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return {}, text
        parts = text.split("---\n", 2)
        if len(parts) != 3:
            return {}, text
        metadata = yaml.safe_load(parts[1]) or {}
        return metadata if isinstance(metadata, dict) else {}, parts[2].strip()

    def _rebuild_index(self) -> None:
        lines: list[str] = []
        for path in sorted(self._dir.glob("*.md")):
            if path.name == "MEMORY.md":
                continue
            try:
                metadata, content = self._read_note(path)
            except (OSError, yaml.YAMLError):
                continue
            note_type = str(metadata.get("type", ""))
            title = str(metadata.get("title", ""))
            description = next((line.strip() for line in content.splitlines() if line.strip()), "")
            if len(description) > 100:
                description = description[:99] + "…"
            lines.append(f"- [{note_type}] {title} — {description}")
        index = "\n".join(lines)
        if index:
            index += "\n"
        (self._dir / "MEMORY.md").write_text(index, encoding="utf-8")
