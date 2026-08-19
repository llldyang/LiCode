"""Team 斜杠命令。"""

from .ui import UI

USAGE = "用法: /team list | info <名称> | delete <名称> [--force] | kill <成员>"


async def handle_team_root(ui: UI) -> None:
    ui.error(USAGE)


async def handle_team(ui: UI, args: str) -> None:
    accessor = ui.team_accessor()
    if accessor is None:
        raise RuntimeError("Team 功能不可用")
    parts = args.split()
    if not parts:
        raise ValueError(USAGE)
    subcommand = parts[0].lower()
    if subcommand == "list" and len(parts) == 1:
        teams = accessor.list()
        if not teams:
            ui.println("暂无 Team")
            return
        for team in teams:
            active = sum(member.is_active is not False for member in team.members)
            ui.println(
                f"{team.name}  {team.backend}  {len(team.members)} 成员  "
                f"[{active}/{len(team.members)}] 活跃"
            )
        return
    if subcommand == "info" and len(parts) == 2:
        team = accessor.info(parts[1])
        ui.println(f"Team {team.name}  后端 {team.backend}  配置 {team.config_path}")
        for member in team.members:
            ui.println(
                f"{member.name}  {member.agent_id}  {member.backend}  "
                f"active={member.is_active}  pane={member.pane_id or '-'}  "
                f"tasks={member.task_count}  {member.worktree_path or '-'}"
            )
        return
    if subcommand == "delete" and len(parts) in {2, 3}:
        if len(parts) == 3 and parts[2] != "--force":
            raise ValueError(USAGE)
        await accessor.delete(parts[1], "--force" in parts[2:])
        ui.println(f"Team 已删除: {parts[1]}")
        return
    if subcommand == "kill" and len(parts) == 2:
        await accessor.kill(parts[1])
        ui.println(f"Team 成员已终止: {parts[1]}")
        return
    raise ValueError(USAGE)
