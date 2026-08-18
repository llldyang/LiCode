"""Hook 四类动作执行器。"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass

import httpx

from .rule import ActionType, HttpAction, Payload, Rule, ShellAction, SubagentAction


@dataclass
class ExecutionResult:
    blocked: bool = False
    reason: str = ""
    prompt: str = ""
    err: Exception | None = None


class Executor:
    def __init__(self, http_client: httpx.AsyncClient | None = None) -> None:
        self._http_client = http_client or httpx.AsyncClient()
        self._owns_http_client = http_client is None

    async def run(self, rule: Rule, payload: Payload, *, blocking: bool) -> ExecutionResult:
        action = rule.action
        if action.type is ActionType.SHELL and action.shell is not None:
            return await self._run_shell(action.shell, payload, blocking, rule.timeout_s)
        if action.type is ActionType.PROMPT and action.prompt is not None:
            return ExecutionResult(prompt=action.prompt.text)
        if action.type is ActionType.HTTP and action.http is not None:
            return await self._run_http(action.http, payload, blocking, rule.timeout_s)
        if action.type is ActionType.SUBAGENT and action.subagent is not None:
            return self._run_subagent(action.subagent)
        return ExecutionResult(err=RuntimeError(f"unknown action type: {action.type.value}"))

    async def _run_shell(
        self,
        action: ShellAction,
        payload: Payload,
        blocking: bool,
        timeout_s: float,
    ) -> ExecutionResult:
        try:
            process = await asyncio.create_subprocess_shell(
                action.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(_marshal_sorted(payload)),
                    timeout=timeout_s,
                )
            except asyncio.CancelledError:
                process.kill()
                await process.wait()
                raise
            except TimeoutError:
                process.kill()
                await process.wait()
                return ExecutionResult(err=TimeoutError(f"timeout after {timeout_s:g}s"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return ExecutionResult(err=exc)

        stderr_text = stderr.decode("utf-8", errors="replace").rstrip("\r\n")
        stdout_text = stdout.decode("utf-8", errors="replace").rstrip("\r\n")
        if blocking and process.returncode == 2:
            return ExecutionResult(blocked=True, reason=stderr_text or stdout_text or "blocked")
        if process.returncode == 0:
            return ExecutionResult()
        return ExecutionResult(
            err=RuntimeError(f"exit {process.returncode}: {stderr_text or stdout_text}")
        )

    async def _run_http(
        self,
        action: HttpAction,
        payload: Payload,
        blocking: bool,
        timeout_s: float,
    ) -> ExecutionResult:
        try:
            body = (
                json.dumps(payload, ensure_ascii=False, sort_keys=True)
                if action.body is None
                else action.body.format_map(payload)
            )
            response = await self._http_client.request(
                action.method or "POST",
                action.url,
                content=body.encode("utf-8"),
                headers=action.headers,
                timeout=timeout_s,
            )
            if not 200 <= response.status_code < 300:
                return ExecutionResult(err=RuntimeError(f"HTTP {response.status_code}"))
            data = response.json()
            if not isinstance(data, dict):
                return ExecutionResult(err=ValueError("HTTP response must be a JSON object"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return ExecutionResult(err=exc)

        if blocking and data.get("decision") == "block":
            return ExecutionResult(blocked=True, reason=str(data.get("reason", "blocked")))
        return ExecutionResult()

    @staticmethod
    def _run_subagent(action: SubagentAction) -> ExecutionResult:
        print(
            f"[hook subagent] not yet implemented, skipped: {action.agent_name}",
            file=sys.stderr,
        )
        return ExecutionResult()

    async def close(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()


def _marshal_sorted(payload: Payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
