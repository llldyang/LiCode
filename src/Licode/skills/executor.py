"""Skill 的 inline 与 fork 执行路径。"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    SessionContext,
)
from Licode.config import ProviderConfig, effective_context_window
from Licode.conversation import Conversation
from Licode.llm import ROLE_ASSISTANT, ROLE_USER, Message, Provider, new_provider
from Licode.permission import Engine
from Licode.tool import Registry

from .active import ActiveSkills
from .catalog import Catalog
from .render import render_body
from .types import Skill

if TYPE_CHECKING:
    from Licode.command import UI

SYSTEM_TOOL_NAMES = frozenset({"LoadSkill"})


class SkillDependencyError(RuntimeError):
    """Skill 的工具白名单引用了未注册工具。"""


def _is_system_tool(tool: object) -> bool:
    return bool(getattr(tool, "is_system", False) or getattr(tool, "is_system_tool", False))


def filter_tool_registry(registry: Registry, allowed: list[str]) -> Registry:
    if not allowed:
        return registry
    missing = [name for name in allowed if registry.get(name) is None]
    if missing:
        raise SkillDependencyError(f"skill requires unknown tool: {', '.join(missing)}")
    allowed_names = set(allowed)
    filtered = Registry()
    for name, tool in registry.items():
        if name in allowed_names or _is_system_tool(tool):
            filtered.register(tool)
    return filtered


class Executor:
    def __init__(
        self,
        catalog: Catalog,
        active: ActiveSkills,
        registry: Registry,
        engine: Engine,
        version: str,
        providers: list[ProviderConfig],
        *,
        instruction_text: str = "",
        memory_text: str = "",
    ) -> None:
        self.catalog = catalog
        self.active = active
        self.registry = registry
        self.engine = engine
        self.version = version
        self.providers = providers
        self.instruction_text = instruction_text
        self.memory_text = memory_text
        self._provider: Provider | None = None
        self._conversation: Conversation | None = None

    def bind(self, provider: Provider, conversation: Conversation) -> None:
        self._provider = provider
        self._conversation = conversation

    async def execute(self, ui: UI, name: str, args: str) -> None:
        skill = self.catalog.get(name)
        if skill is None:
            ui.error(f"unknown skill: {name}")
            return
        if skill.meta.is_fork():
            result = await self.execute_fork(skill, args)
            ui.append_assistant_message(result)
            return
        self.execute_inline(skill, args)
        ui.inject_and_send(f"/{skill.name}", f"请按照已激活的 {skill.name} Skill 执行。")

    def execute_inline(self, skill: Skill, args: str) -> None:
        self.active.activate(skill.name, render_body(skill, args))

    async def execute_fork(self, skill: Skill, args: str) -> str:
        if self._provider is None or self._conversation is None:
            return f"[skill {skill.name} failed: executor not bound]"
        try:
            registry = filter_tool_registry(self.registry, skill.allowed_tools)
            provider, context_window = self._select_provider(skill)
            fork_conv = self._build_fork_conversation(skill)
            fork_conv.add_user(render_body(skill, args))
            return await self._run_fork(
                skill,
                fork_conv,
                registry,
                provider,
                context_window,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return f"[skill {skill.name} failed: {exc}]"

    def _select_provider(self, skill: Skill) -> tuple[Provider, int]:
        if skill.model is None:
            assert self._provider is not None
            matched = next(
                (cfg for cfg in self.providers if cfg.model == self._provider.model),
                None,
            )
            return self._provider, effective_context_window(matched) if matched else 200000
        selected = next(
            (cfg for cfg in self.providers if cfg.name == skill.model or cfg.model == skill.model),
            None,
        )
        if selected is None:
            raise RuntimeError(f"skill model is not configured: {skill.model}")
        return new_provider(selected), effective_context_window(selected)

    def _build_fork_conversation(self, skill: Skill) -> Conversation:
        assert self._conversation is not None
        source = [
            message
            for message in self._conversation.messages()
            if message.role in {ROLE_USER, ROLE_ASSISTANT}
        ]
        if skill.context == "none":
            return Conversation()
        if skill.context == "recent":
            return Conversation.from_messages(source[-5:])
        lines = ["## Previous conversation summary"]
        lines.extend(f"{message.role}: {message.content}" for message in source)
        summary = "\n\n".join(lines)
        return Conversation.from_messages([Message(role=ROLE_USER, content=summary)])

    async def _run_fork(
        self,
        skill: Skill,
        conversation: Conversation,
        registry: Registry,
        provider: Provider,
        context_window: int,
    ) -> str:
        from Licode.agent import SessionRuntime
        from Licode.agent.launch import ForkLaunchOpts, launch_fork

        # Skill fork 的压缩落盘只在临时目录中存在，不能污染主会话归档。
        with tempfile.TemporaryDirectory(prefix="Licode-skill-fork-") as temp_dir:
            session_dir = Path(temp_dir)
            spill_dir = session_dir / "tool-results"
            spill_dir.mkdir()
            runtime = SessionRuntime(
                replacement=ContentReplacementState(),
                recovery=RecoveryState(),
                auto_tracking=CompactCircuitBreaker(),
                session=SessionContext(
                    session_id=f"fork-{skill.name}",
                    session_dir=str(session_dir),
                    spill_dir=str(spill_dir),
                ),
                context_window=context_window,
            )
            return await launch_fork(
                ForkLaunchOpts(
                    allowed_tools=[name for name, _ in registry.items()],
                    model=provider.model,
                    conv=conversation,
                    system_prompt="",
                    background=False,
                    events_sink=None,
                    provider=provider,
                    registry=registry,
                    engine=self.engine,
                    version=self.version,
                    hook_engine=None,
                    runtime=runtime,
                    catalog=self.catalog,
                    instruction_text=self.instruction_text,
                    memory_text=self.memory_text,
                )
            )


SkillExecutor = Executor
