"""iTerm2 Team 后端。"""

from __future__ import annotations

import asyncio
import shlex

from Licode.team.types import BackendType

from . import SpawnRequest
from .tmux import build_member_cmd


class Iterm2Backend:
    def type(self) -> BackendType:
        return BackendType.ITERM2

    async def spawn(self, req: SpawnRequest) -> tuple[str, str]:
        pane_id = (
            await _run_it2("split", "--new-pane", "--command", shlex.join(build_member_cmd(req)))
        ).strip()
        if not pane_id:
            raise RuntimeError("it2 未返回 pane id")
        return pane_id, req.agent_id

    async def wake(self, pane_id: str, agent_id: str) -> None:
        del agent_id
        await _run_it2("send-text", "--pane", pane_id, "")

    async def kill(self, pane_id: str, agent_id: str) -> None:
        del agent_id
        if pane_id:
            await _run_it2("close-pane", "--pane", pane_id, check=False)


async def _run_it2(*args: str, check: bool = True) -> str:
    process = await asyncio.create_subprocess_exec(
        "it2",
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if check and process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"it2 命令失败: {detail}")
    return stdout.decode("utf-8", errors="replace")
