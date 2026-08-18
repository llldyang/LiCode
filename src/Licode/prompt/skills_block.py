"""Skill 的渐进式提示词片段。"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SkillCatalogItem:
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class ActiveSkillEntry:
    name: str
    body: str


def render_skills_catalog(items: list[SkillCatalogItem]) -> str:
    if not items:
        return ""
    lines = ["## Available Skills"]
    lines.extend(f"- {item.name}: {item.description}" for item in items)
    lines.extend(
        (
            "",
            "If the user's request matches a Skill, call LoadSkill with its name to activate it.",
        )
    )
    return "\n".join(lines)


def render_active_skills_block(entries: list[ActiveSkillEntry]) -> str:
    if not entries:
        return ""
    sections = ["## Active Skills"]
    for entry in entries:
        sections.extend((f"### Skill: {entry.name}", entry.body))
    return "\n\n".join(sections)
