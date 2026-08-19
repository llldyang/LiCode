"""后台任务完成与权限升级在 TUI 中的消费逻辑。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from textual.message import Message as TextualMessage

from Licode.task import BackgroundTask

if TYPE_CHECKING:
    from .app import LiCodeApp


class LeadMailMessage(TextualMessage):
    """通知 Textual 主循环处理新到的 Lead 邮件。"""


def build_task_notification(task: BackgroundTask) -> str:
    """构造只注入下一轮模型 reminder 的后台任务通知。"""

    detail = str(task.err) if task.err is not None else task.result
    return (
        "<task-notification>\n"
        f'Task {task.id} (name="{task.name}"): {task.status}\n'
        f"Result: {detail}\n"
        "</task-notification>"
    )


async def consume_task_done(app: LiCodeApp) -> None:
    queue = app.task_mgr.subscribe_done()
    while True:
        task_id = await queue.get()
        task = app.task_mgr.get(task_id)
        if task is not None:
            app.runtime.append_reminders([build_task_notification(task)])


async def consume_subagent_approvals(app: LiCodeApp) -> None:
    """把子 Agent 的 Ask 决策复用到主 TUI 审批面板。"""

    queue = app.task_mgr.subscribe_approvals()
    while True:
        request = await queue.get()
        while app.pending is not None:
            await asyncio.sleep(0.05)
        request.reason = f"[来自 SubAgent] {request.reason}"
        app._show_approval(request)


def build_team_update_reminder(messages) -> str:
    lines = ["<team-update>", f"收到 {len(messages)} 条队员更新:"]
    for index, message in enumerate(messages, 1):
        lines.append(
            f"[{index}] team={message.team_name} 来自 {message.from_} "
            f"(type={message.type.value},ts={message.timestamp}): {message.summary}"
        )
        lines.append("    " + message.content[:8000])
    lines.append("</team-update>")
    return "\n".join(lines)


async def consume_lead_mail(app: LiCodeApp) -> None:
    while True:
        await asyncio.sleep(1.0)
        if app.team_mgr is None:
            continue
        messages = await app.team_mgr.poll_lead_mailboxes()
        if messages:
            app.runtime.append_reminders([build_team_update_reminder(messages)])
            app.lead_mail_event.set()


async def wait_for_lead_mail(app: LiCodeApp) -> None:
    while True:
        await app.lead_mail_event.wait()
        app.lead_mail_event.clear()
        app.post_message(LeadMailMessage())
