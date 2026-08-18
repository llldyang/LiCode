"""Shell 命令执行工具。"""

import asyncio
import json
import os
import signal
import subprocess
from typing import Any

from . import Result, _truncate
from .ctx import resolve_path


class BashTool:
    read_only = False
    is_system = False

    def name(self) -> str:
        return "bash"

    def description(self) -> str:
        return (
            "在当前工作目录执行 shell 命令，返回退出码、标准输出和标准错误。"
            "读文件、找文件、搜内容请优先用 read_file/glob/grep，不要用 bash 拼凑。"
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "要执行的 shell 命令"}},
            "required": ["command"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            return Result(content=f"参数 JSON 非法: {exc}", is_error=True)
        if not isinstance(data, dict) or not isinstance(data.get("command"), str):
            return Result(content="缺少字符串参数: command", is_error=True)

        try:
            if os.name == "nt":
                process = await asyncio.create_subprocess_shell(
                    data["command"],
                    cwd=resolve_path(""),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                process = await asyncio.create_subprocess_shell(
                    data["command"],
                    cwd=resolve_path(""),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                )
        except OSError as exc:
            return Result(content=f"启动命令失败: {exc}", is_error=True)

        try:
            stdout_bytes, stderr_bytes = await process.communicate()
        except asyncio.CancelledError:
            if os.name == "nt":
                killer = await asyncio.create_subprocess_exec(
                    "taskkill",
                    "/F",
                    "/T",
                    "/PID",
                    str(process.pid),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await killer.wait()
            else:
                try:
                    getattr(os, "killpg")(process.pid, getattr(signal, "SIGKILL"))
                except ProcessLookupError:
                    pass
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise

        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")
        output = f"exit_code: {process.returncode}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        return Result(content=_truncate(output, max_lines=10000, max_chars=30000))
