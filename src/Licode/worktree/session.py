"""Worktree 会话状态与原子持久化。"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class WorktreeSession:
    original_cwd: str
    worktree_path: str
    worktree_name: str
    original_branch: str
    original_head_commit: str
    session_id: str
    hook_based: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> WorktreeSession:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("Worktree session 必须是 JSON 对象")
        return cls(**value)


def load_session(path: Path) -> WorktreeSession | None:
    """读取会话；文件不存在、空内容和 null 都表示无活跃会话。"""

    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8").strip()
    if not raw or raw == "null":
        return None
    return WorktreeSession.from_json(raw)


def save_session(path: Path, session: WorktreeSession | None) -> None:
    """通过同目录临时文件原子保存会话。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    content = "null" if session is None else session.to_json()
    temp_path.write_text(content, encoding="utf-8")
    os.replace(temp_path, path)


def clear_session(path: Path) -> None:
    save_session(path, None)
