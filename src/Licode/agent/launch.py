"""Skill 与其他调用方共享的 Fork 运行入口。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from Licode.conversation import Conversation
from Licode.hook import Engine as HookEngine
from Licode.llm import Provider
from Licode.permission import Engine
from Licode.tool import Registry

from . import AgentOutput, SessionRuntime, new_agent

if TYPE_CHECKING:
    from Licode.skills import Catalog


@dataclass
class ForkLaunchOpts:
    allowed_tools: list[str]
    model: str
    conv: Conversation
    system_prompt: str
    background: bool
    events_sink: asyncio.Queue[AgentOutput | None] | None
    provider: Provider
    registry: Registry
    engine: Engine
    version: str
    hook_engine: HookEngine | None
    runtime: SessionRuntime | None = None
    catalog: Catalog | None = None
    instruction_text: str = ""
    memory_text: str = ""


async def launch_fork(options: ForkLaunchOpts) -> str:
    """构造独立运行时并执行一个已经装填消息的 Fork 会话。"""

    runtime = options.runtime or SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(options.engine.root),
        context_window=200000,
    )
    agent = new_agent(
        options.provider,
        options.registry,
        options.version,
        options.engine,
        runtime=runtime,
        hook_engine=options.hook_engine,
        system_prompt=options.system_prompt or None,
        instruction_text=options.instruction_text,
        memory_text=options.memory_text,
        allowed_tools=options.allowed_tools,
        is_sub_agent=True,
    )
    if options.catalog is not None:
        agent.with_catalog(options.catalog)
    return await agent.run_to_completion(options.conv, "", options.events_sink)
