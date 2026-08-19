from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from Licode.team import LeadMessage
from Licode.team.mailbox import MessageType
from Licode.tui.tasks import build_team_update_reminder, consume_lead_mail


class Runtime:
    def __init__(self) -> None:
        self.reminders: list[str] = []

    def append_reminders(self, prompts: list[str]) -> None:
        self.reminders.extend(prompts)


class Manager:
    def __init__(self) -> None:
        self.calls = 0

    async def poll_lead_mailboxes(self):
        self.calls += 1
        if self.calls == 1:
            return [
                LeadMessage("demo", "alice", MessageType.TEXT, "alice idle", "完成 agent.py", 123)
            ]
        return []


@pytest.mark.asyncio
async def test_lead_mail_consumer_appends_reminder_and_sets_event(monkeypatch) -> None:
    original_sleep = asyncio.sleep

    async def immediate_sleep(delay: float) -> None:
        del delay
        await original_sleep(0)

    monkeypatch.setattr("Licode.tui.tasks.asyncio.sleep", immediate_sleep)
    app = SimpleNamespace(team_mgr=Manager(), runtime=Runtime(), lead_mail_event=asyncio.Event())
    consumer = asyncio.create_task(consume_lead_mail(app))
    try:
        await asyncio.wait_for(app.lead_mail_event.wait(), 1)
        assert "<team-update>" in app.runtime.reminders[0]
        assert "agent.py" in app.runtime.reminders[0]
    finally:
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer


def test_team_update_content_is_capped() -> None:
    reminder = build_team_update_reminder(
        [LeadMessage("demo", "alice", MessageType.TEXT, "done", "x" * 9000, 1)]
    )
    assert "x" * 8000 in reminder
    assert "x" * 8001 not in reminder
