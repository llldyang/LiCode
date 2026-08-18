"""统一的 Agent 工具，负责启动定义式或 Fork 子 Agent。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol

from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from Licode.conversation import Conversation
from Licode.subagent import Definition
from Licode.task import Manager, PartialState
from Licode.tool import Result
from Licode.tool.filter import FilterParams, apply_agent_tool_filter
from Licode.worktree import Manager as WorktreeManager

from . import Agent, AgentOutput, Event, Phase, SessionRuntime
from .agent_worktree import execute_with_worktree
from .context import current_agent, current_conversation
from .fork import build_forked_messages, is_fork_context

AUTO_BACKGROUND_SECONDS = 120.0


class AgentCatalog(Protocol):
    def resolve(self, name: str) -> Definition | None: ...

    def fork_definition(self) -> Definition: ...

    def list(self) -> list[Definition]: ...


@dataclass
class AgentArgs:
    prompt: str
    description: str
    subagent_type: str = ""
    model: str = ""
    run_in_background: bool = False
    name: str = ""


def is_sub_agent_context() -> bool:
    caller = current_agent()
    return caller is not None and caller.is_sub_agent


async def aggregate_partial(
    events: asyncio.Queue[AgentOutput | None], partial: PartialState
) -> None:
    """聚合前台阶段的文本、工具和 token 用量。"""

    while True:
        output = await events.get()
        if output is None:
            return
        if not isinstance(output, Event):
            continue
        if output.text:
            partial.last_assistant_text += output.text
        if output.tool is not None and output.tool.phase is Phase.START:
            partial.tool_count += 1
            partial.last_activity = output.tool.name
        if output.usage is not None:
            partial.usage.input += output.usage.input
            partial.usage.output += output.usage.output
            partial.usage.cache_write += output.usage.cache_write
            partial.usage.cache_read += output.usage.cache_read


class AgentTool:
    """把角色选择、运行方式和任务管理收敛为稳定工具 Schema。"""

    read_only = False
    is_system = False

    def __init__(
        self,
        catalog: AgentCatalog,
        task_mgr: Manager,
        parent: Agent | None,
        bg_enabled: bool,
        worktree_mgr: WorktreeManager | None = None,
    ) -> None:
        self.catalog = catalog
        self.task_mgr = task_mgr
        self.parent = parent
        self.bg_enabled = bg_enabled
        self.worktree_mgr = worktree_mgr

    def set_parent(self, agent: Agent) -> None:
        self.parent = agent

    def name(self) -> str:
        return "Agent"

    def description(self) -> str:
        choices = ", ".join(item.name for item in self.catalog.list())
        return (
            "启动一个独立上下文的子 Agent；subagent_type 留空时 Fork 当前对话。"
            f" subagent_type 可选值: {choices}"
        )

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "description": {"type": "string"},
                "subagent_type": {"type": "string"},
                "model": {"type": "string"},
                "run_in_background": {"type": "boolean", "default": False},
                "name": {"type": "string"},
            },
            "required": ["prompt", "description"],
            "additionalProperties": False,
        }

    @staticmethod
    def _parse_args(raw: str) -> AgentArgs:
        try:
            value = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError(f"参数不是有效 JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("参数必须是 JSON 对象")
        return AgentArgs(
            prompt=str(value.get("prompt") or "").strip(),
            description=str(value.get("description") or "").strip(),
            subagent_type=str(value.get("subagent_type") or "").strip(),
            model=str(value.get("model") or "").strip(),
            run_in_background=bool(value.get("run_in_background") or False),
            name=str(value.get("name") or "").strip(),
        )

    def _allowed_tools(self, definition: Definition, background: bool) -> list[str]:
        assert self.parent is not None
        all_names = [name for name, _ in self.parent.registry.items()]
        filtered = apply_agent_tool_filter(
            FilterParams(
                all=all_names,
                source=int(definition.source),
                background=background,
                allowed=definition.tools,
                disallowed=definition.disallowed_tools,
            )
        )
        if definition.is_fork() and "Agent" in all_names:
            selected = set(filtered)
            selected.add("Agent")
            return [name for name in all_names if name in selected]
        return filtered

    def _new_sub_agent(self, definition: Definition, allowed: list[str]) -> Agent:
        assert self.parent is not None
        runtime = SessionRuntime(
            replacement=ContentReplacementState(),
            recovery=RecoveryState(),
            auto_tracking=CompactCircuitBreaker(),
            session=new_session_context(self.parent.engine.root),
            context_window=200000,
        )
        return Agent(
            self.parent.provider,
            self.parent.registry,
            self.parent.version,
            self.parent.engine,
            runtime=runtime,
            hook_engine=self.parent.hook_engine,
            system_prompt=definition.system_prompt or None,
            max_turns=definition.max_turns,
            permission_mode=definition.permission_mode,
            dont_ask=definition.dont_ask,
            approval_upgrader=self.task_mgr.upgrade_approval,
            allowed_tools=allowed,
            is_sub_agent=True,
        )

    async def execute(self, args: str) -> Result:
        try:
            parsed = self._parse_args(args)
        except ValueError as exc:
            return Result(str(exc), is_error=True)
        if not parsed.prompt:
            return Result("prompt is required", is_error=True)
        if not parsed.description:
            return Result("description is required", is_error=True)
        if self.parent is None:
            return Result("Agent tool parent is not initialized", is_error=True)

        caller_conversation = current_conversation()
        if caller_conversation is not None and is_fork_context(caller_conversation.messages()):
            return Result("Fork 子 Agent 不能再启动 Agent", is_error=True)
        if is_sub_agent_context():
            return Result("SubAgent 不能再启动 Agent", is_error=True)

        if parsed.subagent_type:
            definition = self.catalog.resolve(parsed.subagent_type)
            if definition is None:
                return Result(
                    f"unknown subagent_type: {parsed.subagent_type}",
                    is_error=True,
                )
        else:
            definition = self.catalog.fork_definition()

        isolated = definition.isolation == "worktree"
        if isolated and self.worktree_mgr is None:
            return Result("worktree manager not configured", is_error=True)
        background = (
            definition.background or parsed.run_in_background or definition.is_fork()
        ) and not isolated
        if background and not self.bg_enabled:
            return Result("background mode is disabled by config", is_error=True)
        allowed = self._allowed_tools(definition, background)
        sub_agent = self._new_sub_agent(definition, allowed)

        task_for_run = parsed.prompt
        if definition.is_fork():
            parent_conversation = self.parent.current_conversation
            parent_messages = (
                caller_conversation.messages()
                if caller_conversation is not None
                else (parent_conversation.messages() if parent_conversation is not None else [])
            )
            sub_conv = Conversation.from_messages(
                build_forked_messages(parent_messages, parsed.prompt)
            )
            task_for_run = ""
        else:
            sub_conv = Conversation()

        if background:
            task_id = await self.task_mgr.launch(
                sub_agent,
                sub_conv,
                parsed.name,
                parsed.prompt,
            )
            return Result(json.dumps({"task_id": task_id, "status": "async_launched"}))

        events: asyncio.Queue[AgentOutput | None] = asyncio.Queue(maxsize=64)
        partial = PartialState()
        aggregator = asyncio.create_task(aggregate_partial(events, partial))
        if isolated:
            assert self.worktree_mgr is not None
            run = execute_with_worktree(
                self.worktree_mgr,
                definition,
                sub_agent,
                sub_conv,
                task_for_run,
                events,
            )
        else:
            run = sub_agent.run_to_completion(sub_conv, task_for_run, events)
        handle = asyncio.create_task(run)
        adopted = False
        try:
            if isolated:
                final_text = await handle
            else:
                final_text = await asyncio.wait_for(
                    asyncio.shield(handle), timeout=AUTO_BACKGROUND_SECONDS
                )
        except TimeoutError:
            aggregator.cancel()
            try:
                await aggregator
            except asyncio.CancelledError:
                pass
            task_id = await self.task_mgr.adopt_running(
                sub_agent,
                sub_conv,
                parsed.name,
                events,
                handle,
                partial,
                parsed.prompt,
            )
            adopted = True
            return Result(json.dumps({"task_id": task_id, "status": "timed_out_to_background"}))
        except asyncio.CancelledError:
            handle.cancel()
            raise
        except Exception as exc:
            return Result(f"subagent error: {exc}", is_error=True)
        finally:
            if not adopted:
                if not handle.done():
                    handle.cancel()
                try:
                    events.put_nowait(None)
                except asyncio.QueueFull:
                    aggregator.cancel()
                try:
                    await aggregator
                except asyncio.CancelledError:
                    pass
        return Result(final_text)
