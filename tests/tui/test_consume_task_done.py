import asyncio

import pytest

from Licode.conversation import Conversation
from Licode.task import Manager
from Licode.tui.tasks import build_task_notification, consume_task_done


class FakeAgent:
    async def run_to_completion(self, conv, task, events=None):
        return "ok"


class ReminderRuntime:
    def __init__(self) -> None:
        self.reminders: list[str] = []

    def append_reminders(self, prompts: list[str]) -> None:
        self.reminders.extend(prompts)


class FakeApp:
    def __init__(self) -> None:
        self.task_mgr = Manager()
        self.runtime = ReminderRuntime()


@pytest.mark.asyncio
async def test_consume_task_done_injects_notification() -> None:
    app = FakeApp()
    consumer = asyncio.create_task(consume_task_done(app))
    try:
        task_id = await app.task_mgr.launch(FakeAgent(), Conversation(), "worker", "task")
        for _ in range(20):
            if app.runtime.reminders:
                break
            await asyncio.sleep(0)
        assert app.runtime.reminders
        notification = app.runtime.reminders[0]
        assert notification.startswith("<task-notification>")
        assert task_id in notification
        assert "completed" in notification
        task = app.task_mgr.get(task_id)
        assert task is not None
        assert build_task_notification(task) == notification
    finally:
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
