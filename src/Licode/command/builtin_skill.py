"""Skill Catalog 的本地查看命令。"""

from .ui import UI


async def handle_skill(ui: UI) -> None:
    skills = ui.list_catalog_skills()
    if not skills:
        ui.println("无已加载 Skill")
        return
    width = max(len(skill.name) for skill in skills)
    lines = [
        f"{skill.name.ljust(width)}  {skill.description}  [{skill.source}/{skill.mode}]"
        for skill in skills
    ]
    active = ui.list_active_skills()
    if active:
        lines.extend(("", "Active: " + ", ".join(active)))
    ui.println("\n".join(lines))
