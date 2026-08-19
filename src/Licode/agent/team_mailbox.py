"""在队员每轮模型调用前注入未读 Team 邮件。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from Licode.permission import Mode

if TYPE_CHECKING:
    from . import Agent
    from .team_hook import IncomingMessage


async def ingest_team_mailbox(agent: Agent) -> None:
    context = agent.team_context
    if context is None:
        return
    indices, messages = await context.read_unread()
    if not messages:
        return
    approval_notes: list[str] = []
    for message in messages:
        if message.type != "plan_approval_response":
            continue
        payload = message.payload or {}
        if payload.get("approve") is True:
            agent.set_permission_mode(Mode.DEFAULT)
            approval_notes.append("Lead 已批准计划，权限模式已切到 default，可执行计划。")
        else:
            feedback = str(payload.get("feedback", ""))
            approval_notes.append(f"Lead 驳回了计划，反馈：{feedback}。请调整后重新提交。")
    agent.runtime.append_reminders([build_incoming_messages_reminder(messages, approval_notes)])
    await context.mark_read(indices)


def build_incoming_messages_reminder(
    messages: list[IncomingMessage], approval_notes: list[str] | None = None
) -> str:
    lines = ["<incoming-messages>", f"收到 {len(messages)} 条新消息:"]
    for index, message in enumerate(messages, 1):
        timestamp = datetime.fromtimestamp(message.timestamp).isoformat(timespec="seconds")
        lines.append(
            f"[{index}] 来自 {message.from_}(type={message.type},ts={timestamp}): {message.summary}"
        )
        lines.append(f"    {message.content[:200]}")
    lines.extend(approval_notes or [])
    lines.append("</incoming-messages>")
    return "\n".join(lines)


__all__ = ["build_incoming_messages_reminder", "ingest_team_mailbox"]
