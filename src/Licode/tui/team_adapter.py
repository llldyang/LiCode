"""Team Manager 到斜杠命令协议的适配层。"""

from Licode.command import TeamMemberSummary, TeamSummary
from Licode.team import Manager
from Licode.team.backend import new_backend
from Licode.team.persistence import read_json
from Licode.team.types import TeamNotFoundError


class TeamAdapter:
    def __init__(self, manager: Manager) -> None:
        self.manager = manager

    def list(self) -> list[TeamSummary]:
        return [self._summary(team) for team in self.manager.list_()]

    def info(self, name: str) -> TeamSummary:
        team = self.manager.get(name)
        if team is None:
            raise TeamNotFoundError(f"Team 不存在: {name}")
        return self._summary(team)

    async def delete(self, name: str, force: bool) -> None:
        await self.manager.delete(name, force)

    async def kill(self, member_name: str) -> None:
        found = self.manager.find_member(member_name)
        if found is None:
            raise ValueError(f"Team 成员不存在: {member_name}")
        team, member = found
        if member.name == "lead":
            raise ValueError("不能终止 Lead")
        backend = new_backend(member.backend_type, task_mgr=self.manager.task_mgr)
        await backend.kill(member.pane_id, member.agent_id)
        # 成员从花名册移除后 Team 删除流程无法再发现其资源，因此必须在这里先清理。
        await self.manager._cleanup_member_resources(team, member)
        await team.remove_member(member.name)
        self.manager.registry.unregister(member.name)

    @staticmethod
    def _summary(team) -> TeamSummary:
        counts: dict[str, int] = {}
        try:
            value = read_json(team.tasks_path)
            tasks = value.get("tasks", []) if isinstance(value, dict) else []
            for task in tasks:
                assignee = task.get("assignee", "") if isinstance(task, dict) else ""
                if isinstance(assignee, str) and assignee:
                    counts[assignee] = counts.get(assignee, 0) + 1
        except (OSError, TypeError, ValueError):
            pass
        return TeamSummary(
            name=team.sanitized_name,
            backend=team.backend.value,
            config_path=team.config_path,
            members=[
                TeamMemberSummary(
                    name=member.name,
                    agent_id=member.agent_id,
                    backend=member.backend_type.value,
                    worktree_path=member.worktree_path,
                    pane_id=member.pane_id,
                    is_active=member.is_active,
                    task_count=counts.get(member.name, 0),
                )
                for member in team.members
            ],
        )


__all__ = ["TeamAdapter"]
