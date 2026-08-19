"""Hook 规则的有序事件分派引擎。"""

from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass, field

from .event import Event, is_blocking
from .executor import ExecutionResult, Executor
from .matcher import eval_condition
from .rule import Payload, Rule


@dataclass
class DispatchResult:
    blocked: bool = False
    reason: str = ""
    blocking_hook_name: str = ""
    injected_prompts: list[str] = field(default_factory=list)


class Engine:
    def __init__(
        self,
        rules: list[Rule],
        sources: list[str],
        executor: Executor | None = None,
    ) -> None:
        self._rules = list(rules)
        self._sources = list(sources)
        self._once_fired: set[tuple[str, str]] = set()
        self._once_running: set[tuple[str, str]] = set()
        self._session_generations: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._executor = executor or Executor()
        self._background: set[asyncio.Task[None]] = set()

    async def dispatch(self, event: Event, payload: Payload) -> DispatchResult:
        event_payload = dict(payload)
        event_payload["event"] = event.value
        result = DispatchResult()
        for rule in self._rules:
            if rule.event is not event:
                continue
            if not eval_condition(rule.condition, event_payload):
                continue

            once_token = await self._claim_once(rule, event_payload)
            if once_token is None:
                continue

            if rule.asyncio_mode:
                task = asyncio.create_task(self._run_background(rule, event_payload, once_token))
                self._background.add(task)
                task.add_done_callback(self._background.discard)
                continue

            try:
                outcome = await self._executor.run(
                    rule,
                    event_payload,
                    blocking=is_blocking(event),
                )
            except asyncio.CancelledError:
                await self._finish_once(rule, once_token, succeeded=False)
                raise
            except Exception as exc:
                outcome = ExecutionResult(err=exc)
            if outcome.err is not None:
                self._log_failure(rule, outcome)
                await self._finish_once(rule, once_token, succeeded=False)
                continue
            if outcome.prompt:
                result.injected_prompts.append(outcome.prompt)
            await self._finish_once(rule, once_token, succeeded=True)
            if outcome.blocked and is_blocking(event):
                result.blocked = True
                result.reason = outcome.reason
                result.blocking_hook_name = rule.name
                break
        return result

    async def _claim_once(
        self,
        rule: Rule,
        payload: Payload,
    ) -> tuple[str, int] | None:
        """原子占用 only_once 规则，避免并发事件重复启动同一动作。"""

        async with self._lock:
            session_id = str(payload.get("session_id", ""))
            generation = self._session_generations.setdefault(session_id, 0)
            if not rule.only_once:
                return session_id, generation
            key = (session_id, rule.name)
            if key in self._once_fired or key in self._once_running:
                return None
            self._once_running.add(key)
            return session_id, generation

    async def _finish_once(
        self,
        rule: Rule,
        token: tuple[str, int],
        *,
        succeeded: bool,
    ) -> None:
        if not rule.only_once:
            return
        async with self._lock:
            session_id, generation = token
            # 上一会话的后台动作结束时，不能污染已经重置的新会话。
            if generation != self._session_generations.get(session_id, 0):
                return
            key = (session_id, rule.name)
            self._once_running.discard(key)
            if succeeded:
                self._once_fired.add(key)

    async def _run_background(
        self,
        rule: Rule,
        payload: Payload,
        once_token: tuple[str, int],
    ) -> None:
        try:
            outcome = await self._executor.run(rule, payload, blocking=False)
        except asyncio.CancelledError:
            await self._finish_once(rule, once_token, succeeded=False)
            raise
        except Exception as exc:
            outcome = ExecutionResult(err=exc)
        if outcome.err is not None:
            self._log_failure(rule, outcome)
            await self._finish_once(rule, once_token, succeeded=False)
            return
        await self._finish_once(rule, once_token, succeeded=True)

    @staticmethod
    def _log_failure(rule: Rule, outcome: ExecutionResult) -> None:
        print(
            f"[hook {rule.name}] {rule.event.value} failed: {outcome.err}",
            file=sys.stderr,
        )

    async def reset_for_new_session(self, session_id: str | None = None) -> None:
        async with self._lock:
            if session_id is None:
                session_ids = set(self._session_generations)
                self._once_fired.clear()
                self._once_running.clear()
            else:
                session_ids = {session_id}
                self._once_fired = {key for key in self._once_fired if key[0] != session_id}
                self._once_running = {key for key in self._once_running if key[0] != session_id}
            for current_id in session_ids:
                self._session_generations[current_id] = (
                    self._session_generations.get(current_id, 0) + 1
                )

    async def wait_background(self) -> None:
        if self._background:
            await asyncio.gather(*tuple(self._background))

    async def close(self) -> None:
        await self.wait_background()
        await self._executor.close()

    @property
    def sources(self) -> list[str]:
        return list(self._sources)

    @property
    def rules(self) -> list[Rule]:
        return list(self._rules)
