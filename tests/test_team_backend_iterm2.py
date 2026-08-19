from __future__ import annotations

import pytest

from Licode.team.backend import SpawnRequest
from Licode.team.backend.iterm2 import Iterm2Backend


def request() -> SpawnRequest:
    return SpawnRequest(
        "demo",
        "alice",
        "agent-1",
        "/repo/wt",
        "/repo/session",
        "general-purpose",
        "",
        "secret prompt",
        False,
    )


@pytest.mark.asyncio
async def test_iterm2_commands(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    async def fake_run(*args: str, check: bool = True) -> str:
        calls.append((*args, f"check={check}"))
        return "pane-1\n"

    monkeypatch.setattr("Licode.team.backend.iterm2._run_it2", fake_run)
    backend = Iterm2Backend()
    assert await backend.spawn(request()) == ("pane-1", "agent-1")
    await backend.wake("pane-1", "agent-1")
    await backend.kill("pane-1", "agent-1")
    assert calls[0][:3] == ("split", "--new-pane", "--command")
    assert "--agent-id agent-1" in calls[0][3]
    assert "secret prompt" not in calls[0][3]
    assert calls[1][:3] == ("send-text", "--pane", "pane-1")
    assert calls[2][:3] == ("close-pane", "--pane", "pane-1")
