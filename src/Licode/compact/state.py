"""上下文管理的会话级状态。"""

from __future__ import annotations

import copy
import logging
import random
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .const import MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SessionContext:
    session_id: str
    session_dir: str
    spill_dir: str


def _new_session_id() -> str:
    try:
        suffix = secrets.token_hex(2)
    except Exception as exc:
        logger.warning("生成安全随机会话标识失败，使用时间种子降级: %s", exc)
        suffix = random.Random(time.time()).randbytes(2).hex()
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{suffix}"


def new_session_context(workspace: str) -> SessionContext:
    """创建本进程使用的会话目录。"""

    session_id = _new_session_id()
    session_dir = Path(workspace).resolve() / ".Licode" / "sessions" / session_id
    spill_dir = session_dir / "tool-results"
    spill_dir.mkdir(parents=True, exist_ok=True)
    return SessionContext(
        session_id=session_id,
        session_dir=str(session_dir),
        spill_dir=str(spill_dir),
    )


def open_session_context(workspace: str, session_id: str) -> SessionContext:
    """打开已经存在的会话目录。"""

    session_dir = Path(workspace).resolve() / ".Licode" / "sessions" / session_id
    if not session_dir.is_dir():
        raise FileNotFoundError(f"会话目录不存在: {session_dir}")
    spill_dir = session_dir / "tool-results"
    spill_dir.mkdir(parents=True, exist_ok=True)
    return SessionContext(
        session_id=session_id,
        session_dir=str(session_dir),
        spill_dir=str(spill_dir),
    )


def parse_session_time(session_id: str) -> datetime:
    """从新格式会话 ID 解析本地创建时间。"""

    import re

    if re.fullmatch(r"\d{8}-\d{6}-[0-9a-f]{4}", session_id) is None:
        raise ValueError(f"无效的会话 ID: {session_id}")
    return datetime.strptime(session_id[:15], "%Y%m%d-%H%M%S")


class ContentReplacementState:
    """冻结每个工具结果的保留或替换决策。"""

    def __init__(self) -> None:
        self._seen_ids: set[str] = set()
        self._replacements: dict[str, str] = {}
        self._lock = threading.RLock()

    def has_decision(self, tool_use_id: str) -> bool:
        with self._lock:
            return tool_use_id in self._seen_ids

    def replacement_for(self, tool_use_id: str) -> str | None:
        with self._lock:
            return self._replacements.get(tool_use_id)

    def decide_once(
        self,
        tool_use_id: str,
        original: str,
        decide: Callable[[], tuple[str, str]],
    ) -> str:
        """原子完成查询、首次决策与账本写入。"""

        with self._lock:
            if tool_use_id in self._seen_ids:
                return self._replacements.get(tool_use_id, original)

            decision, preview = decide()
            if decision == "kept":
                self._seen_ids.add(tool_use_id)
                return original
            if decision == "replaced":
                self._replacements[tool_use_id] = preview
                self._seen_ids.add(tool_use_id)
                return preview
            if decision == "skip":
                return original
            raise ValueError(f"未知的替换决策: {decision}")

    def replacement_count(self) -> int:
        with self._lock:
            return len(self._replacements)


class CompactCircuitBreaker:
    """记录自动摘要连续失败次数。"""

    def __init__(self) -> None:
        self._consecutive_failures = 0
        self._lock = threading.RLock()

    def record_success(self) -> None:
        with self._lock:
            self._consecutive_failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1

    def tripped(self) -> bool:
        with self._lock:
            return self._consecutive_failures >= MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES


@dataclass(frozen=True)
class FileReadRecord:
    path: str
    content: str
    timestamp: datetime


class RecoveryState:
    """并发安全地追踪最近成功读取的文件原文。"""

    def __init__(self) -> None:
        self._files: dict[str, FileReadRecord] = {}
        self._lock = threading.RLock()

    def record_file(self, path: str, content: str) -> None:
        absolute = str(Path(path).resolve())
        with self._lock:
            self._files[absolute] = FileReadRecord(
                path=absolute,
                content=content,
                timestamp=datetime.now(),
            )

    def snapshot(self) -> list[FileReadRecord]:
        with self._lock:
            records = [copy.copy(record) for record in self._files.values()]
        return sorted(records, key=lambda record: record.timestamp, reverse=True)
