"""后台任务完成与权限升级在 TUI 中的消费逻辑。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from Licode.task import BackgroundTask

if TYPE_CHECKING:
    from .app import LiCodeApp


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
