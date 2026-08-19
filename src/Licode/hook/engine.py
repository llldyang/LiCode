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
        self._once_fired: set[str] = set()
        self._once_running: set[str] = set()
        self._session_generation = 0
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

            generation = await self._claim_once(rule)
            if generation is None:
                continue

            if rule.asyncio_mode:
                task = asyncio.create_task(self._run_background(rule, event_payload, generation))
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
                await self._finish_once(rule, generation, succeeded=False)
                raise
            except Exception as exc:
                outcome = ExecutionResult(err=exc)
            if outcome.err is not None:
                self._log_failure(rule, outcome)
                await self._finish_once(rule, generation, succeeded=False)
                continue
            if outcome.prompt:
                result.injected_prompts.append(outcome.prompt)
            await self._finish_once(rule, generation, succeeded=True)
            if outcome.blocked and is_blocking(event):
                result.blocked = True
                result.reason = outcome.reason
                result.blocking_hook_name = rule.name
                break
        return result

    async def _claim_once(self, rule: Rule) -> int | None:
        """原子占用 only_once 规则，避免并发事件重复启动同一动作。"""

        async with self._lock:
            generation = self._session_generation
            if not rule.only_once:
                return generation
            if rule.name in self._once_fired or rule.name in self._once_running:
                return None
            self._once_running.add(rule.name)
            return generation

    async def _finish_once(self, rule: Rule, generation: int, *, succeeded: bool) -> None:
        if not rule.only_once:
            return
        async with self._lock:
            # 上一会话的后台动作结束时，不能污染已经重置的新会话。
            if generation != self._session_generation:
                return
            self._once_running.discard(rule.name)
            if succeeded:
                self._once_fired.add(rule.name)

    async def _run_background(
        self,
        rule: Rule,
        payload: Payload,
        generation: int,
    ) -> None:
        try:
            outcome = await self._executor.run(rule, payload, blocking=False)
        except asyncio.CancelledError:
            await self._finish_once(rule, generation, succeeded=False)
            raise
        except Exception as exc:
            outcome = ExecutionResult(err=exc)
        if outcome.err is not None:
            self._log_failure(rule, outcome)
            await self._finish_once(rule, generation, succeeded=False)
            return
        await self._finish_once(rule, generation, succeeded=True)

    @staticmethod
    def _log_failure(rule: Rule, outcome: ExecutionResult) -> None:
        print(
            f"[hook {rule.name}] {rule.event.value} failed: {outcome.err}",
            file=sys.stderr,
        )

    async def reset_for_new_session(self) -> None:
        async with self._lock:
            self._session_generation += 1
            self._once_fired.clear()
            self._once_running.clear()

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
