"""Pane 后端队员使用的无 TUI 自治循环。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from Licode.agent import Agent, ApprovalRequest, Event, Phase, SessionRuntime
from Licode.agent.team_hook import IncomingMessage, TeammateContext
from Licode.compact import CompactCircuitBreaker, ContentReplacementState, RecoveryState
from Licode.compact.state import SessionContext
from Licode.config import effective_context_window
from Licode.conversation import Conversation
from Licode.llm import new_provider
from Licode.permission import Mode
from Licode.session import Writer, load_session
from Licode.team.mailbox import Box, Message, MessageType
from Licode.team.spawn import build_team_context_reminder, team_system_prompt_suffix
from Licode.tool.filter import FilterParams, apply_agent_tool_filter


async def run_team_member(
    args: Any,
    config: Any,
    registry: Any,
    engine: Any,
    hook_engine: Any,
    team_mgr: Any,
    subagent_catalog: Any,
    agent_tool: Any,
) -> int:
    _validate_args(args)
    team = team_mgr.get(args.team)
    if team is None:
        raise ValueError(f"Team 不存在: {args.team}")
    definition = subagent_catalog.resolve(args.agent_type or "general-purpose")
    if definition is None:
        raise ValueError(f"Agent 定义不存在: {args.agent_type or 'general-purpose'}")
    provider_cfg = config.providers[0]
    provider = new_provider(provider_cfg)
    session_dir = Path(args.session_dir).resolve()
    spill_dir = session_dir / "tool-results"
    spill_dir.mkdir(parents=True, exist_ok=True)
    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=SessionContext(session_dir.name, str(session_dir), str(spill_dir)),
        context_window=effective_context_window(provider_cfg),
    )
    writer = Writer.open_existing(str(session_dir))
    writer.set_model(provider.model)
    box = Box(team.mailbox_dir)

    async def read_unread() -> tuple[list[int], list[IncomingMessage]]:
        indices, messages = await box.read_unread(args.agent_id)
        return indices, [
            IncomingMessage(
                from_=message.from_,
                type=message.type.value,
                summary=message.summary,
                content=message.content,
                timestamp=message.timestamp,
                payload=message.payload,
            )
            for message in messages
        ]

    async def mark_read(indices: list[int]) -> None:
        await box.mark_read(args.agent_id, indices)

    context = TeammateContext(
        team_name=team.sanitized_name,
        member_name=args.member,
        agent_id=args.agent_id,
        backend_type=team.backend,
        mailbox_dir=team.mailbox_dir,
        read_unread=read_unread,
        mark_read=mark_read,
    )
    all_names = [name for name, _ in registry.items()]
    allowed = apply_agent_tool_filter(
        FilterParams(
            all=all_names,
            source=int(definition.source),
            background=False,
            allowed=definition.tools,
            disallowed=definition.disallowed_tools,
            teammate=True,
        )
    )
    # Pane 队员可启动普通子 Agent，但 AgentTool 会拒绝其 team_name 分支。
    if "Agent" in all_names and "Agent" not in allowed:
        allowed.append("Agent")
    system_prompt = "\n\n".join(
        part for part in (definition.system_prompt, team_system_prompt_suffix()) if part
    )
    conversation = Conversation.from_messages(
        load_session(str(session_dir)),
        on_append=writer.on_append,
        on_replace=writer.on_replace,
    )
    runtime.append_reminders(
        [
            build_team_context_reminder(
                team,
                args.member,
                args.agent_id,
                args.worktree,
                args.agent_type,
            )
        ]
    )
    agent = Agent(
        provider,
        registry,
        "team-member",
        engine,
        runtime=runtime,
        hook_engine=hook_engine,
        system_prompt=system_prompt,
        max_turns=definition.max_turns,
        permission_mode=Mode.PLAN if args.plan_mode else definition.permission_mode,
        dont_ask=True,
        allowed_tools=allowed,
        is_sub_agent=True,
        team_context=context,
        working_directory=args.worktree,
    )
    agent_tool.set_parent(agent)
    wake_event = asyncio.Event()
    stdin_task = asyncio.create_task(_read_stdin(wake_event))
    print(
        f"[team-member] {args.member} · team={team.sanitized_name} · "
        f"agent={args.agent_id} · cwd={args.worktree}",
        flush=True,
    )
    try:
        while Path(team.mailbox_dir).is_dir():
            indices, messages = await box.read_unread(args.agent_id)
            if not messages:
                try:
                    await asyncio.wait_for(wake_event.wait(), timeout=2.0)
                except TimeoutError:
                    pass
                wake_event.clear()
                continue
            await box.mark_read(args.agent_id, indices)
            task_parts: list[str] = []
            shutdown = False
            for message in messages:
                if message.type is MessageType.TEXT:
                    task_parts.append(message.content)
                elif message.type is MessageType.PLAN_APPROVAL_RESPONSE:
                    payload = message.payload or {}
                    if payload.get("approve") is True:
                        agent.set_permission_mode(Mode.DEFAULT)
                        task_parts.append("Lead 已批准计划，请继续执行。")
                    else:
                        task_parts.append(
                            f"Lead 驳回了计划，请根据反馈调整：{payload.get('feedback', '')}"
                        )
                elif message.type is MessageType.SHUTDOWN_REQUEST:
                    shutdown = True
            if shutdown:
                break
            task_text = "\n\n".join(part for part in task_parts if part)
            if not task_text:
                continue
            await _run_and_print(agent, conversation, task_text)
            await _mark_idle(team, args.member)
            await box.write(
                team.lead_agent_id,
                Message(
                    from_=args.member,
                    to="lead",
                    type=MessageType.TEXT,
                    summary=f"{args.member} idle",
                    content=f"agent {args.agent_id} finished work, available for new tasks",
                ),
            )
    finally:
        stdin_task.cancel()
        writer.close()
    return 0


async def _run_and_print(agent: Agent, conversation: Conversation, task: str) -> None:
    events: asyncio.Queue = asyncio.Queue(maxsize=64)
    handle = asyncio.create_task(agent.run_to_completion(conversation, task, events))
    while not handle.done() or not events.empty():
        try:
            output = await asyncio.wait_for(events.get(), timeout=0.1)
        except TimeoutError:
            continue
        if isinstance(output, ApprovalRequest):
            continue
        if not isinstance(output, Event):
            continue
        if output.text:
            print(output.text, end="", flush=True)
        if output.tool is not None and output.tool.phase is Phase.START:
            print(f"\n● {output.tool.name}({output.tool.args})", flush=True)
        if output.err is not None:
            print(f"\n错误: {output.err}", file=sys.stderr, flush=True)
        if output.done:
            print("\n----------------------------------------", flush=True)
    await handle


async def _mark_idle(team: Any, member_name: str) -> None:
    # Lead 可能尚未完成 add_member；短暂重试以覆盖 Pane 启动竞态。
    for _ in range(20):
        try:
            await team.set_member_active(member_name, False)
            return
        except Exception:
            await asyncio.sleep(0.1)


async def _read_stdin(wake_event: asyncio.Event) -> None:
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if line == "":
            return
        wake_event.set()


def _validate_args(args: Any) -> None:
    for name in ("team", "member", "agent_id", "session_dir", "worktree"):
        if not getattr(args, name, ""):
            raise ValueError(f"--team-member 需要 --{name.replace('_', '-')}")


__all__ = ["run_team_member"]
