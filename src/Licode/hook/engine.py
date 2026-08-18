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
            async with self._lock:
                if rule.only_once and rule.name in self._once_fired:
                    continue
            if not eval_condition(rule.condition, event_payload):
                continue

            if rule.asyncio_mode:
                task = asyncio.create_task(self._run_background(rule, event_payload))
                self._background.add(task)
                task.add_done_callback(self._background.discard)
                if rule.only_once:
                    async with self._lock:
                        self._once_fired.add(rule.name)
                continue

            outcome = await self._executor.run(
                rule,
                event_payload,
                blocking=is_blocking(event),
            )
            if outcome.err is not None:
                self._log_failure(rule, outcome)
                continue
            if outcome.prompt:
                result.injected_prompts.append(outcome.prompt)
            if rule.only_once:
                async with self._lock:
                    self._once_fired.add(rule.name)
            if outcome.blocked and is_blocking(event):
                result.blocked = True
                result.reason = outcome.reason
                result.blocking_hook_name = rule.name
                break
        return result

    async def _run_background(self, rule: Rule, payload: Payload) -> None:
        try:
            outcome = await self._executor.run(rule, payload, blocking=False)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            outcome = ExecutionResult(err=exc)
        if outcome.err is not None:
            self._log_failure(rule, outcome)

    @staticmethod
    def _log_failure(rule: Rule, outcome: ExecutionResult) -> None:
        print(
            f"[hook {rule.name}] {rule.event.value} failed: {outcome.err}",
            file=sys.stderr,
        )

    async def reset_for_new_session(self) -> None:
        async with self._lock:
            self._once_fired.clear()

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
