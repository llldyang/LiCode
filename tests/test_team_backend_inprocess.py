import pytest

from Licode.team.backend import SpawnRequest
from Licode.team.backend.inprocess import InProcessBackend


class TaskManager:
    def __init__(self) -> None:
        self.launch_args = None
        self.stopped = ""

    async def launch(self, *args):
        self.launch_args = args
        return "task_123"

    async def stop(self, task_id: str) -> bool:
        self.stopped = task_id
        return True


@pytest.mark.asyncio
async def test_inprocess_backend_launch_wake_and_kill() -> None:
    manager = TaskManager()
    backend = InProcessBackend(manager)
    request = SpawnRequest(
        "demo",
        "alice",
        "agent-1",
        "/wt",
        "/session",
        "worker",
        "",
        "task",
        False,
        sub_agent=object(),
        conv=object(),
    )
    assert await backend.spawn(request) == ("", "task_123")
    assert manager.launch_args[2:] == ("alice", "task")
    await backend.wake("", "task_123")
    await backend.kill("", "task_123")
    assert manager.stopped == "task_123"
