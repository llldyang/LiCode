"""把 Skill Catalog 暴露为斜杠短命令。"""

import logging

from Licode.skills import Catalog
from Licode.skills.executor import Executor

from .command import Command, Handler, Kind
from .registry import Registry
from .ui import UI

logger = logging.getLogger(__name__)
_SKILL_DESCRIPTION_SUFFIX = " [skill]"


def _handler(executor: Executor, name: str) -> Handler:
    async def execute_skill(ui: UI) -> None:
        await executor.execute(ui, name, "")

    return execute_skill


def register_skills_as_commands(
    registry: Registry,
    catalog: Catalog,
    executor: Executor,
) -> None:
    for skill in catalog.list():
        if registry.lookup(skill.name) is not None:
            logger.warning("Skipping skill command '%s': command name conflict", skill.name)
            continue
        registry.register(
            Command(
                skill.name,
                skill.description + _SKILL_DESCRIPTION_SUFFIX,
                Kind.PROMPT,
                _handler(executor, skill.name),
            )
        )


def remove_skill_commands(registry: Registry) -> None:
    registry.remove_all(lambda command: command.description.endswith(_SKILL_DESCRIPTION_SUFFIX))
