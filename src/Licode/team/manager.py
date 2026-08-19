"""Team 生命周期、恢复与 Lead 邮箱协调。"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .backend import new_backend
from .backend.detect import detect
from .mailbox import Box, Message, MessageType
from .persistence import atomic_write_json, bind_team_paths, read_json, sanitize, team_from_dict
from .registry import AgentNameRegistry
from .types import (
    BackendType,
    Team,
    TeamHasActiveMembersError,
    TeammateInfo,
    TeamNotFoundError,
)

if TYPE_CHECKING:
    from Licode.task import Manager as TaskManager
    from Licode.worktree import Manager as WorktreeManager


@dataclass
class LeadMessage:
    team_name: str
    from_: str
    type: MessageType
    summary: str
    content: str
    timestamp: int


class Manager:
    """在一个 LiCode 进程内管理多个持久化 Team。"""

    def __init__(
        self,
        home_dir: str | Path,
        project_root: str | Path,
        wt_mgr: WorktreeManager | None,
        task_mgr: TaskManager,
        reg: AgentNameRegistry,
    ) -> None:
        self.home_dir = str(Path(home_dir).resolve())
        self.project_root = str(Path(project_root).resolve())
        self.wt_mgr = wt_mgr
        self.task_mgr = task_mgr
        self.registry = reg
        self.teams_dir = str(Path(self.home_dir) / ".Licode" / "teams")
        self.teams: dict[str, Team] = {}
        self._lock = asyncio.Lock()
        self._agent_tool: Any = None
        self._config: Any = None
        self._session_writers: dict[str, Any] = {}
        self.coordinator_mode = False
        Path(self.teams_dir).mkdir(parents=True, exist_ok=True)
        self._restore_teams()

    def configure_spawn(self, agent_tool: Any, config: Any) -> None:
        """在 CLI 完成循环依赖对象构造后绑定 spawn 所需依赖。"""

        self._agent_tool = agent_tool
        self._config = config

    def _restore_teams(self) -> None:
        for directory in sorted(Path(self.teams_dir).iterdir()):
            if not directory.is_dir():
                continue
            try:
                team = team_from_dict(read_json(directory / "config.json"), directory)
            except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                print(f"跳过损坏的 Team 配置 {directory}: {exc}", file=sys.stderr)
                continue
            # 进程重启后没有可恢复的 asyncio task，in-process 成员必须视为空闲。
            changed = False
            for member in team.members:
                if member.backend_type is BackendType.IN_PROCESS and member.name != "lead":
                    changed = changed or member.is_active is not False
                    member.is_active = False
                elif member.name != "lead" and member.is_active is not False:
                    if not _pane_is_alive(member):
                        changed = True
                        member.is_active = False
                if member.name:
                    self.registry.register(member.name, member.agent_id)
            if changed:
                try:
                    atomic_write_json(team.config_path, team.to_dict())
                except OSError as exc:
                    print(f"Team 恢复状态写回失败 {team.name}: {exc}", file=sys.stderr)
            self.teams[team.sanitized_name] = team

    def get(self, name: str) -> Team | None:
        return self.teams.get(name) or self.teams.get(sanitize(name))

    def list_(self) -> list[Team]:
        return sorted(self.teams.values(), key=lambda item: item.created_at)

    async def create(self, name: str, description: str = "") -> Team:
        base = sanitize(name)
        if not base:
            raise ValueError("Team 名称清理后不能为空")
        async with self._lock:
            selected = base
            suffix = 2
            while selected in self.teams or (Path(self.teams_dir) / selected).exists():
                selected = f"{base}-{suffix}"
                suffix += 1
            directory = Path(self.teams_dir) / selected
            try:
                directory.mkdir(parents=False)
                (directory / "mailbox").mkdir()
                team = bind_team_paths(
                    Team(
                        name=name,
                        sanitized_name=selected,
                        lead_agent_id="lead",
                        backend=detect(),
                        description=description,
                        members=[
                            TeammateInfo(
                                name="lead",
                                agent_id="lead",
                                backend_type=BackendType.IN_PROCESS,
                                is_active=None,
                            )
                        ],
                    ),
                    directory,
                )
                atomic_write_json(team.config_path, team.to_dict())
            except BaseException:
                shutil.rmtree(directory, ignore_errors=True)
                raise
            self.teams[selected] = team
            self.registry.register("lead", "lead")
            return team

    async def delete(self, name: str, force: bool = False) -> None:
        async with self._lock:
            team = self.get(name)
            if team is None:
                raise TeamNotFoundError(f"Team 不存在: {name}")
            if not force and any(member.is_active is not False for member in team.members):
                raise TeamHasActiveMembersError(f"Team 仍有活跃成员: {team.sanitized_name}")

            for member in list(team.members):
                if member.name == "lead":
                    continue
                try:
                    backend = new_backend(member.backend_type, task_mgr=self.task_mgr)
                    await backend.kill(member.pane_id, member.agent_id)
                except Exception as exc:
                    print(f"终止 Team 成员 {member.name} 失败: {exc}", file=sys.stderr)
                await self._cleanup_member_resources(team, member)
                self.registry.unregister(member.name)

            try:
                shutil.rmtree(team.config_dir)
            except FileNotFoundError:
                pass
            self.registry.unregister("lead")
            self.teams.pop(team.sanitized_name, None)

    async def _cleanup_member_resources(self, team: Team, member: TeammateInfo) -> None:
        writer = self._session_writers.pop(member.agent_id, None)
        if writer is not None:
            try:
                writer.close()
            except Exception as exc:
                print(f"关闭成员会话 {member.name} 失败: {exc}", file=sys.stderr)
        if member.session_dir:
            shutil.rmtree(member.session_dir, ignore_errors=True)
        if self.wt_mgr is None or not member.worktree_path:
            return
        worktree_name = f"team-{team.sanitized_name}/{member.name}"
        try:
            from Licode.worktree import ExitOptions

            await self.wt_mgr.remove(worktree_name, ExitOptions(discard_changes=True))
        except Exception as exc:
            print(f"删除成员 Worktree {member.name} 失败: {exc}", file=sys.stderr)

    def find_member(self, name_or_id: str) -> tuple[Team, TeammateInfo] | None:
        agent_id = self.registry.resolve(name_or_id) or name_or_id
        for team in self.teams.values():
            member = team.member_by_agent_id(agent_id) or team.member_by_name(name_or_id)
            if member is not None:
                return team, member
        return None

    def current_team(self) -> Team:
        """队员按上下文寻址；Lead 使用最近创建的 Team。"""

        from Licode.agent.team_hook import teammate_context_from_ctx

        context = teammate_context_from_ctx()
        if context is not None:
            team = self.get(context.team_name)
            if team is None:
                raise TeamNotFoundError(f"Team 不存在: {context.team_name}")
            return team
        teams = self.list_()
        if not teams:
            raise TeamNotFoundError("当前没有 Team")
        return teams[-1]

    async def handle_task_done(self, agent_id: str) -> None:
        found = self.find_member(agent_id)
        if found is None:
            return
        team, member = found
        if member.name == "lead":
            return
        try:
            await team.set_member_active(member.name, False)
            await Box(team.mailbox_dir).write(
                team.lead_agent_id,
                Message(
                    from_=member.name,
                    to="lead",
                    type=MessageType.TEXT,
                    summary=f"{member.name} idle",
                    content=f"agent {member.agent_id} finished work, available for new tasks",
                ),
            )
        except Exception as exc:
            print(f"记录成员空闲状态失败 {member.name}: {exc}", file=sys.stderr)

    async def poll_lead_mailboxes(self) -> list[LeadMessage]:
        async with self._lock:
            result: list[LeadMessage] = []
            for team in self.list_():
                box = Box(team.mailbox_dir)
                indices, messages = await box.read_unread(team.lead_agent_id)
                if not messages:
                    continue
                result.extend(
                    LeadMessage(
                        team_name=team.sanitized_name,
                        from_=message.from_,
                        type=message.type,
                        summary=message.summary,
                        content=message.content,
                        timestamp=message.timestamp,
                    )
                    for message in messages
                )
                await box.mark_read(team.lead_agent_id, indices)
            return result

    async def spawn_teammate(self, request: Any) -> str:
        from .spawn import spawn_teammate

        return await spawn_teammate(self, request)

    def is_teammate_context(self) -> tuple[str, str, bool]:
        from Licode.agent.team_hook import teammate_context_from_ctx

        context = teammate_context_from_ctx()
        if context is None:
            return "", "", False
        return (
            context.team_name,
            context.member_name,
            context.backend_type is BackendType.IN_PROCESS,
        )


def _pane_is_alive(member: TeammateInfo) -> bool:
    """启动恢复阶段同步探测 Pane；失败时保守地标为空闲。"""

    if not member.pane_id:
        return False
    if member.backend_type is BackendType.TMUX:
        command = ["tmux", "list-panes", "-a", "-F", "#{pane_id}"]
    elif member.backend_type is BackendType.ITERM2:
        command = ["it2", "list-panes"]
    else:
        return False
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0 and member.pane_id in result.stdout.split()
