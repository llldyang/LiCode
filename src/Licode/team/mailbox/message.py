"""Team 邮箱消息格式。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class MessageType(StrEnum):
    TEXT = "text"
    SHUTDOWN_REQUEST = "shutdown_request"
    SHUTDOWN_RESPONSE = "shutdown_response"
    PLAN_APPROVAL_RESPONSE = "plan_approval_response"


@dataclass
class Message:
    from_: str
    to: str
    type: MessageType
    summary: str
    content: str
    payload: dict[str, Any] | None = None
    timestamp: int = 0
    read: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "from": self.from_,
            "to": self.to,
            "type": self.type.value,
            "summary": self.summary,
            "content": self.content,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "read": self.read,
        }

    @classmethod
    def from_dict(cls, value: object) -> Message:
        if not isinstance(value, dict):
            raise ValueError("邮箱消息必须是 JSON 对象")
        payload = value.get("payload")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("payload 必须是对象或 null")
        timestamp = value.get("timestamp", 0)
        if isinstance(timestamp, bool) or not isinstance(timestamp, int):
            raise ValueError("timestamp 必须是整数")
        read = value.get("read", False)
        if not isinstance(read, bool):
            raise ValueError("read 必须是布尔值")
        return cls(
            from_=_string(value, "from"),
            to=_string(value, "to"),
            type=MessageType(value.get("type", MessageType.TEXT.value)),
            summary=_string(value, "summary", allow_empty=True),
            content=_string(value, "content", allow_empty=True),
            payload=payload,
            timestamp=timestamp,
            read=read,
        )


def _string(value: dict[str, Any], key: str, *, allow_empty: bool = False) -> str:
    item = value.get(key, "")
    if not isinstance(item, str) or (not allow_empty and not item):
        raise ValueError(f"{key} 必须是字符串")
    return item
