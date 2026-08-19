"""把 Agent 工具请求转换为持久化 Team 队员。"""

from __future__ import annotations

import json
import secrets
import shutil
from pathlib import Path

from Licode.agent import Agent, SessionRuntime
from Licode.agent.context import current_conversation
from Licode.agent.fork import build_forked_messages
from Licode.agent.team_hook import IncomingMessage, TeammateContext, TeamSpawnRequest
from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from Licode.conversation import Conversation
from Licode.permission import Mode
from Licode.session import Writer
from Licode.task import RUNNING
from Licode.worktree import ExitOptions

from .backend import SpawnRequest, new_backend
from .feature import fork_teammate_enabled
from .mailbox import Box, Message, MessageType
from .types import BackendType, Team, TeammateInfo, TeamNotFoundError

TEAM_SYSTEM_PROMPT_SUFFIX = """
IMPORTANT: You are running as an agent in a team.
Just writing a response in text is not visible to others
on your team - you MUST use the SendMessage tool.
The user interacts primarily with the team lead.
Your work is coordinated through the task system
and teammate messaging.
""".strip()


async def spawn_teammate(manager, request: TeamSpawnRequest) -> str:
    team = manager.get(request.team_name)
    if team is None:
        raise TeamNotFoundError(f"Team 不存在: {request.team_name}")
    if manager.wt_mgr is None:
        raise RuntimeError("Worktree 管理器未配置")
    agent_tool = manager._agent_tool
    if agent_tool is None or agent_tool.parent is None:
        raise RuntimeError("Agent 工具尚未完成 Team spawn 配置")

    member_name = request.member_name or f"agent-{secrets.token_hex(3)}"
    if team.member_by_name(member_name) is not None:
        raise ValueError(f"Team 成员已存在: {member_name}")
    definition = _resolve_definition(manager, request)
    plan_required = request.plan_mode_required or definition.plan_mode_required
    worktree_name = f"team-{team.sanitized_name}/{member_name}"
    worktree = await manager.wt_mgr.create(worktree_name, "HEAD", manual=False)
    session_context = new_session_context(manager.project_root)
    writer = Writer(session_context.session_dir)
    writer.set_model(agent_tool.parent.provider.model)
    box = Box(team.mailbox_dir)
    initial_agent_id = f"agent-{secrets.token_hex(7)}"
    id_holder = {"value": initial_agent_id}

    async def read_unread() -> tuple[list[int], list[IncomingMessage]]:
        indices, messages = await box.read_unread(id_holder["value"])
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
        await box.mark_read(id_holder["value"], indices)

    teammate_context = TeammateContext(
        team_name=team.sanitized_name,
        member_name=member_name,
        agent_id=initial_agent_id,
        backend_type=team.backend,
        mailbox_dir=team.mailbox_dir,
        read_unread=read_unread,
        mark_read=mark_read,
    )
    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=session_context,
        context_window=agent_tool.parent.runtime.context_window,
    )
    allowed = agent_tool._allowed_tools(definition, False, teammate=True)
    system_prompt = "\n\n".join(
        part for part in (definition.system_prompt, TEAM_SYSTEM_PROMPT_SUFFIX) if part
    )
    sub_agent = Agent(
        agent_tool.parent.provider,
        agent_tool.parent.registry,
        agent_tool.parent.version,
        agent_tool.parent.engine,
        runtime=runtime,
        hook_engine=agent_tool.parent.hook_engine,
        system_prompt=system_prompt,
        max_turns=definition.max_turns,
        permission_mode=Mode.PLAN if plan_required else definition.permission_mode,
        # Team 队员没有可交互审批界面，必须避免 Ask 永久悬挂。
        dont_ask=True,
        allowed_tools=allowed,
        is_sub_agent=True,
        team_context=teammate_context,
        working_directory=worktree.path,
    )

    task_text = request.prompt
    if definition.is_fork():
        parent_conv = current_conversation() or agent_tool.parent.current_conversation
        messages = build_forked_messages(
            parent_conv.messages() if parent_conv is not None else [], request.prompt
        )
        conversation = Conversation.from_messages(
            messages,
            on_append=writer.on_append,
            on_replace=writer.on_replace,
        )
        writer.append_all(messages)
        task_text = ""
    else:
        conversation = Conversation(on_append=writer.on_append, on_replace=writer.on_replace)

    backend = new_backend(team.backend, task_mgr=manager.task_mgr)
    spawn_request = SpawnRequest(
        team_name=team.sanitized_name,
        member_name=member_name,
        agent_id=initial_agent_id,
        worktree_path=worktree.path,
        session_dir=session_context.session_dir,
        agent_type=definition.name if not definition.is_fork() else "",
        model=request.model,
        initial_prompt=task_text,
        plan_mode_required=plan_required,
        sub_agent=sub_agent if team.backend is BackendType.IN_PROCESS else None,
        conv=conversation if team.backend is BackendType.IN_PROCESS else None,
        task_mgr=manager.task_mgr,
    )
    mailbox_path = Path(team.mailbox_dir) / f"{initial_agent_id}.json"
    spawned = False
    pane_id = ""
    agent_id = initial_agent_id
    try:
        if team.backend is not BackendType.IN_PROCESS:
            await box.write(
                initial_agent_id,
                Message(
                    from_="lead",
                    to=member_name,
                    type=MessageType.TEXT,
                    summary=truncate_for_summary(request.prompt),
                    content=request.prompt,
                ),
            )
        pane_id, agent_id = await backend.spawn(spawn_request)
        spawned = True
        id_holder["value"] = agent_id
        teammate_context.agent_id = agent_id
        if team.backend is BackendType.IN_PROCESS:
            # TaskManager 在 spawn 时才确定最终 ID；事件循环再次让出前先写入 reminder，
            # 保证队员首轮看到的 agent_id 与花名册、续派任务使用的是同一个值。
            runtime.append_reminders(
                [
                    build_team_context_reminder(
                        team,
                        member_name,
                        agent_id,
                        worktree.path,
                        spawn_request.agent_type,
                    )
                ]
            )
        member = TeammateInfo(
            name=member_name,
            agent_id=agent_id,
            agent_type=spawn_request.agent_type,
            model=request.model,
            worktree_path=worktree.path,
            branch=worktree.branch,
            backend_type=team.backend,
            pane_id=pane_id,
            is_active=True,
            plan_mode_required=plan_required,
            session_dir=session_context.session_dir,
        )
        await team.add_member(member)
        manager.registry.register(member_name, agent_id)
        manager._session_writers[agent_id] = writer
        background_task = manager.task_mgr.get(agent_id)
        if background_task is not None and background_task.status is not RUNNING:
            await manager.handle_task_done(agent_id)
    except BaseException:
        if spawned:
            try:
                await backend.kill(pane_id, agent_id)
            except Exception:
                pass
        writer.close()
        mailbox_path.unlink(missing_ok=True)
        shutil.rmtree(session_context.session_dir, ignore_errors=True)
        try:
            await manager.wt_mgr.remove(worktree_name, ExitOptions(discard_changes=True))
        except Exception:
            pass
        raise

    return json.dumps(
        {
            "member_name": member_name,
            "agent_id": agent_id,
            "worktree": worktree.path,
            "backend": team.backend.value,
            "pane_id": pane_id,
        },
        ensure_ascii=False,
    )


def _resolve_definition(manager, request: TeamSpawnRequest):
    catalog = manager._agent_tool.catalog
    if request.subagent_type:
        definition = catalog.resolve(request.subagent_type)
        if definition is None:
            raise ValueError(f"未知 subagent_type: {request.subagent_type}")
        return definition
    if fork_teammate_enabled(manager._config):
        return catalog.fork_definition()
    definition = catalog.resolve("general-purpose")
    if definition is None:
        raise ValueError("缺少内置 general-purpose Agent 定义")
    return definition


def build_team_context_reminder(
    team: Team,
    member_name: str,
    agent_id: str,
    worktree_path: str,
    agent_type: str = "",
) -> str:
    member_labels = [f"{member.name}({member.agent_type or 'lead'})" for member in team.members]
    if team.member_by_name(member_name) is None:
        # Pane 可能在 Lead 持久化成员前启动，首条上下文仍应包含队员自己。
        member_labels.append(f"{member_name}({agent_type or 'general-purpose'})")
    members = ", ".join(member_labels)
    return (
        "<team-context>\n"
        f"team: {team.sanitized_name}\n"
        f"你的成员名: {member_name}\n"
        f"你的 agent_id: {agent_id}\n"
        f"worktree 目录: {worktree_path}\n"
        f"当前团队成员: {members}\n"
        "</team-context>"
    )


def truncate_for_summary(prompt: str) -> str:
    words = prompt.split()
    if words:
        return " ".join(words[:10])
    return prompt[:40] or "initial task"


def team_system_prompt_suffix() -> str:
    return TEAM_SYSTEM_PROMPT_SUFFIX


__all__ = [
    "build_team_context_reminder",
    "spawn_teammate",
    "team_system_prompt_suffix",
    "truncate_for_summary",
]
