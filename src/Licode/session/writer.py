"""崩溃安全的 JSONL 会话写入器。"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from Licode.llm import Message

logger = logging.getLogger(__name__)


@dataclass
class Entry:
    role: str = ""
    content: str = ""
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[dict[str, Any]] | None = None
    ts: int = 0
    model: str | None = None
    type: str | None = None


class Writer:
    """以追加方式实时持久化 Conversation 消息。"""

    def __init__(self, session_dir: str) -> None:
        self.session_dir = str(Path(session_dir).resolve())
        Path(self.session_dir).mkdir(parents=True, exist_ok=True)
        self.path = str(Path(self.session_dir) / "conversation.jsonl")
        self._file = open(self.path, "ab")
        self._lock = threading.Lock()
        self._model = ""

    @classmethod
    def open_existing(cls, session_dir: str) -> Writer:
        path = Path(session_dir).resolve()
        if not path.is_dir():
            raise FileNotFoundError(f"会话目录不存在: {path}")
        return cls(str(path))

    def set_model(self, model: str) -> None:
        self._model = model

    def append(self, msg: Message, model: str = "", is_first: bool = False) -> None:
        entry = Entry(
            role=msg.role,
            content=msg.content,
            tool_calls=[asdict(call) for call in msg.tool_calls] or None,
            tool_results=[asdict(result) for result in msg.tool_results] or None,
            ts=int(time.time()),
            model=model if is_first else None,
        )
        self._write_entries([self._entry_dict(entry)])

    def write_compact_marker(self) -> None:
        self._write_entries([{"type": "compact", "ts": int(time.time())}])

    def append_all(self, msgs: list[Message]) -> None:
        entries = [
            self._entry_dict(
                Entry(
                    role=msg.role,
                    content=msg.content,
                    tool_calls=[asdict(call) for call in msg.tool_calls] or None,
                    tool_results=[asdict(result) for result in msg.tool_results] or None,
                    ts=int(time.time()),
                )
            )
            for msg in msgs
        ]
        self._write_entries(entries)

    def on_append(self, msg: Message) -> None:
        try:
            with self._lock:
                is_first = self._file.tell() == 0
                entry = Entry(
                    role=msg.role,
                    content=msg.content,
                    tool_calls=[asdict(call) for call in msg.tool_calls] or None,
                    tool_results=[asdict(result) for result in msg.tool_results] or None,
                    ts=int(time.time()),
                    model=self._model if is_first else None,
                )
                self._write_unlocked([self._entry_dict(entry)])
        except Exception as exc:
            logger.warning("会话消息写入失败: %s", exc)

    def on_replace(self, msgs: list[Message]) -> None:
        try:
            with self._lock:
                entries: list[dict[str, Any]] = [{"type": "compact", "ts": int(time.time())}]
                entries.extend(
                    self._entry_dict(
                        Entry(
                            role=msg.role,
                            content=msg.content,
                            tool_calls=[asdict(call) for call in msg.tool_calls] or None,
                            tool_results=[asdict(result) for result in msg.tool_results] or None,
                            ts=int(time.time()),
                        )
                    )
                    for msg in msgs
                )
                self._write_unlocked(entries)
        except Exception as exc:
            logger.warning("会话压缩记录写入失败: %s", exc)

    def close(self) -> None:
        with self._lock:
            if not self._file.closed:
                self._file.close()

    def __enter__(self) -> Writer:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _write_entries(self, entries: list[dict[str, Any]]) -> None:
        with self._lock:
            self._write_unlocked(entries)

    def _write_unlocked(self, entries: list[dict[str, Any]]) -> None:
        if self._file.closed:
            raise ValueError("会话写入器已关闭")
        for entry in entries:
            data = (json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
                "utf-8"
            )
            self._file.write(data)
            self._file.flush()
            os.fsync(self._file.fileno())

    @staticmethod
    def _entry_dict(entry: Entry) -> dict[str, Any]:
        value = asdict(entry)
        return {
            key: item
            for key, item in value.items()
            if item is not None and not (key == "content" and item == "")
        }
