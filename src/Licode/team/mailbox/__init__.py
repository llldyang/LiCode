"""基于 JSON 文件的 Team 邮箱。"""

from __future__ import annotations

import time
from pathlib import Path

from Licode.team.filelock import acquire
from Licode.team.persistence import atomic_write_json, read_json

from .message import Message, MessageType


class Box:
    def __init__(self, dir_: str) -> None:
        self._dir = str(Path(dir_).resolve())
        Path(self._dir).mkdir(parents=True, exist_ok=True)

    def _message_path(self, agent_id: str) -> Path:
        if not agent_id or any(char in agent_id for char in "/\\"):
            raise ValueError("agent_id 不能包含路径分隔符")
        return Path(self._dir) / f"{agent_id}.json"

    def _read_unlocked(self, path: Path) -> list[Message]:
        try:
            value = read_json(path)
        except FileNotFoundError:
            return []
        if not isinstance(value, dict) or not isinstance(value.get("messages"), list):
            raise ValueError(f"邮箱文件格式无效: {path}")
        return [Message.from_dict(item) for item in value["messages"]]

    async def write(self, agent_id: str, msg: Message) -> None:
        path = self._message_path(agent_id)
        async with acquire(path.with_suffix(".lock")):
            messages = self._read_unlocked(path)
            if msg.timestamp == 0:
                msg.timestamp = int(time.time())
            messages.append(msg)
            atomic_write_json(path, {"messages": [item.to_dict() for item in messages]})

    async def read(self, agent_id: str) -> list[Message]:
        path = self._message_path(agent_id)
        async with acquire(path.with_suffix(".lock")):
            return self._read_unlocked(path)

    async def read_unread(self, agent_id: str) -> tuple[list[int], list[Message]]:
        path = self._message_path(agent_id)
        async with acquire(path.with_suffix(".lock")):
            messages = self._read_unlocked(path)
            indices = [index for index, message in enumerate(messages) if not message.read]
            return indices, [messages[index] for index in indices]

    async def mark_read(self, agent_id: str, indices: list[int]) -> None:
        path = self._message_path(agent_id)
        async with acquire(path.with_suffix(".lock")):
            messages = self._read_unlocked(path)
            for index in indices:
                if 0 <= index < len(messages):
                    messages[index].read = True
            atomic_write_json(path, {"messages": [item.to_dict() for item in messages]})


__all__ = ["Box", "Message", "MessageType"]
