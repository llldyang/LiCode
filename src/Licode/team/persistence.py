"""Team 名称与 JSON 持久化。"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .types import BackendType, Team, TeammateInfo

_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize(name: str) -> str:
    return _UNSAFE_NAME.sub("-", name).strip("-")


def atomic_write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def bind_team_paths(team: Team, config_dir: str | Path) -> Team:
    directory = Path(config_dir).resolve()
    team.config_dir = str(directory)
    team.config_path = str(directory / "config.json")
    team.tasks_path = str(directory / "tasks.json")
    team.mailbox_dir = str(directory / "mailbox")
    return team


def team_from_dict(value: object, config_dir: str | Path) -> Team:
    if not isinstance(value, dict):
        raise ValueError("Team config 必须是 JSON 对象")
    members_raw = value.get("members", [])
    if not isinstance(members_raw, list):
        raise ValueError("members 必须是数组")
    created_at = value.get("created_at", 0)
    if isinstance(created_at, bool) or not isinstance(created_at, (int, float)):
        raise ValueError("created_at 必须是时间戳")
    team = Team(
        name=_text(value, "name", required=True),
        sanitized_name=_text(value, "sanitized_name", required=True),
        lead_agent_id=_text(value, "lead_agent_id", required=True),
        backend=BackendType(value.get("backend", BackendType.IN_PROCESS.value)),
        description=_text(value, "description"),
        created_at=datetime.fromtimestamp(created_at),
        members=[TeammateInfo.from_dict(item) for item in members_raw if isinstance(item, dict)],
    )
    if len(team.members) != len(members_raw):
        raise ValueError("members 包含非对象元素")
    return bind_team_paths(team, config_dir)


async def reload_from_disk_locked(team: Team) -> None:
    """调用方已持 Team 锁；只刷新跨进程可能竞争的成员字段。"""

    try:
        latest = team_from_dict(read_json(team.config_path), team.config_dir)
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return
    team.members = latest.members


def _text(value: dict[str, object], key: str, *, required: bool = False) -> str:
    item = value.get(key, "")
    if not isinstance(item, str) or (required and not item):
        suffix = "非空字符串" if required else "字符串"
        raise ValueError(f"{key} 必须是{suffix}")
    return item
