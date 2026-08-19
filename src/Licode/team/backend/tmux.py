"""tmux Team 后端。"""

from __future__ import annotations

import asyncio
import os
import shlex
import sys

from Licode.team.types import BackendType

from . import SpawnRequest


def build_member_cmd(req: SpawnRequest) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "Licode",
        "--team-member",
        "--team",
        req.team_name,
        "--member",
        req.member_name,
        "--agent-id",
        req.agent_id,
        "--session-dir",
        req.session_dir,
        "--worktree",
        req.worktree_path,
    ]
    if req.agent_type:
        command.extend(("--agent-type", req.agent_type))
    if req.model:
        command.extend(("--model", req.model))
    if req.plan_mode_required:
        command.append("--plan-mode")
    return command


class TmuxBackend:
    def type(self) -> BackendType:
        return BackendType.TMUX

    async def spawn(self, req: SpawnRequest) -> tuple[str, str]:
        if os.environ.get("TMUX"):
            args = ["split-window", "-h", "-P", "-F", "#{pane_id}", "--"]
            pane_id = (await _run_tmux(*args, *build_member_cmd(req))).strip()
        else:
            args = ["new-session", "-d", "-P", "-F", "#{pane_id}"]
            # new-session 只接收一个 shell-command 参数，必须先安全拼成单个命令串。
            pane_id = (await _run_tmux(*args, shlex.join(build_member_cmd(req)))).strip()
        if not pane_id:
            raise RuntimeError("tmux 未返回 pane id")
        return pane_id, req.agent_id

    async def wake(self, pane_id: str, agent_id: str) -> None:
        del agent_id
        await _run_tmux("send-keys", "-t", pane_id, "", "Enter")

    async def kill(self, pane_id: str, agent_id: str) -> None:
        del agent_id
        if not pane_id:
            return
        await _run_tmux("kill-pane", "-t", pane_id, check=False)


async def _run_tmux(*args: str, check: bool = True) -> str:
    process = await asyncio.create_subprocess_exec(
        "tmux",
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if check and process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"tmux 命令失败: {detail}")
    return stdout.decode("utf-8", errors="replace")
