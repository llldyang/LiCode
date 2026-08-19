from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from Licode.team.filelock import acquire
from Licode.team.mailbox import Box, Message, MessageType


@pytest.mark.asyncio
async def test_mailbox_round_trip_and_mark_read(tmp_path: Path) -> None:
    box = Box(str(tmp_path))
    await box.write(
        "agent-1",
        Message("lead", "alice", MessageType.TEXT, "hello there", "正文"),
    )

    indices, unread = await box.read_unread("agent-1")
    assert indices == [0]
    assert unread[0].from_ == "lead"
    assert unread[0].content == "正文"

    await box.mark_read("agent-1", indices)
    assert (await box.read("agent-1"))[0].read is True


@pytest.mark.asyncio
async def test_mailbox_ten_concurrent_writers_do_not_lose_messages(tmp_path: Path) -> None:
    box = Box(str(tmp_path))

    async def write(index: int) -> None:
        await box.write(
            "agent-1",
            Message("lead", "alice", MessageType.TEXT, f"message {index}", str(index)),
        )

    await asyncio.gather(*(write(index) for index in range(10)))
    assert {message.content for message in await box.read("agent-1")} == {
        str(index) for index in range(10)
    }


@pytest.mark.asyncio
async def test_stale_file_lock_can_be_reclaimed(tmp_path: Path) -> None:
    lock_path = tmp_path / "mail.lock"
    lock_path.write_text("stale", encoding="utf-8")
    old = time.time() - 11
    os.utime(lock_path, (old, old))

    async with acquire(lock_path):
        assert lock_path.exists()
    assert not lock_path.exists()
