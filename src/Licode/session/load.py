"""从 JSONL 会话记录恢复协议消息。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from Licode.llm import Message, ToolCall, ToolResult


def _valid_entries(session_dir: str) -> list[dict[str, Any]]:
    path = Path(session_dir) / "conversation.jsonl"
    entries: list[dict[str, Any]] = []
    last_compact = -1
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "compact":
            last_compact = len(entries)
        entries.append(entry)
    if last_compact >= 0:
        return entries[last_compact + 1 :]
    return entries


def load_session(session_dir: str) -> list[Message]:
    messages: list[Message] = []
    for entry in _valid_entries(session_dir):
        role = entry.get("role")
        if role not in {"user", "assistant", "tool"}:
            continue
        try:
            calls = [ToolCall(**item) for item in entry.get("tool_calls") or []]
            results = [ToolResult(**item) for item in entry.get("tool_results") or []]
        except (TypeError, ValueError):
            continue
        messages.append(
            Message(
                role=role,
                content=str(entry.get("content", "")),
                tool_calls=calls,
                tool_results=results,
            )
        )
    return _truncate_orphaned_tool_calls(messages)


def load_session_timestamp(session_dir: str) -> int:
    """返回最后一条有效消息的写入时间。"""

    timestamps = [entry.get("ts") for entry in _valid_entries(session_dir) if entry.get("role")]
    return next((value for value in reversed(timestamps) if isinstance(value, int)), 0)


def _truncate_orphaned_tool_calls(messages: list[Message]) -> list[Message]:
    result = list(messages)
    for index, message in enumerate(result):
        if message.role != "assistant" or not message.tool_calls:
            continue
        if index + 1 >= len(result) or result[index + 1].role != "tool":
            return result[:index]
        expected = {call.id for call in message.tool_calls}
        actual = {item.tool_call_id for item in result[index + 1].tool_results}
        if not expected.issubset(actual):
            return result[:index]
    return result
