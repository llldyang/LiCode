"""把 Skill 内部类型转换为 prompt 包的窄接口。"""

from Licode.prompt.skills_block import ActiveSkillEntry, SkillCatalogItem

from .active import ActiveSkills
from .types import Skill


def to_prompt_items(skills: list[Skill]) -> list[SkillCatalogItem]:
    return [SkillCatalogItem(skill.name, skill.description) for skill in skills]


def to_prompt_entries(active: ActiveSkills) -> list[ActiveSkillEntry]:
    return [ActiveSkillEntry(entry.name, entry.body) for entry in active.snapshot()]
