"""LiCode 终端界面。"""

from Licode.agent import SessionRuntime
from Licode.agent.agent_tool import AgentTool
from Licode.config import ProviderConfig
from Licode.hook import Engine as HookEngine
from Licode.memory import Manager as MemoryManager
from Licode.permission import Engine
from Licode.session import Writer
from Licode.skills import Catalog
from Licode.subagent import Catalog as SubagentCatalog
from Licode.task import Manager as TaskManager
from Licode.tool import Registry
from Licode.tool.install_skill import InstallSkillTool
from Licode.worktree import Manager as WorktreeManager

from .app import LiCodeApp, SessionState


def new_app(
    providers: list[ProviderConfig],
    version: str,
    registry: Registry,
    engine: Engine,
    runtime: SessionRuntime | None = None,
    writer: Writer | None = None,
    memory_manager: MemoryManager | None = None,
    instruction_text: str = "",
    memory_text: str = "",
    sessions_dir: str | None = None,
    catalog: Catalog | None = None,
    install_skill_tool: InstallSkillTool | None = None,
    hook_engine: HookEngine | None = None,
    task_mgr: TaskManager | None = None,
    subagent_catalog: SubagentCatalog | None = None,
    agent_tool: AgentTool | None = None,
    worktree_mgr: WorktreeManager | None = None,
) -> LiCodeApp:
    return LiCodeApp(
        providers,
        version,
        registry,
        engine,
        runtime,
        writer,
        memory_manager,
        instruction_text,
        memory_text,
        sessions_dir,
        catalog,
        install_skill_tool,
        hook_engine,
        task_mgr,
        subagent_catalog,
        agent_tool,
        worktree_mgr,
    )


__all__ = ["LiCodeApp", "SessionState", "new_app"]
