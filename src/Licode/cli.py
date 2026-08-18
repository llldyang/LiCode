"""LiCode 命令行入口。"""

import asyncio
import os
import sys
from contextlib import suppress
from datetime import timedelta
from pathlib import Path

from Licode import (
    __version__,
    config,
    hook,
    instructions,
    memory,
    permission,
    session,
    skills,
    subagent,
    task,
)
from Licode import mcp as mcp_client
from Licode.agent import AgentTool, SessionRuntime
from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from Licode.config import ConfigError
from Licode.tool import new_default_registry
from Licode.tool.install_skill import InstallSkillTool
from Licode.tool.load_skill import LoadSkillTool
from Licode.tui import new_app


async def _amain() -> int:
    writer: session.Writer | None = None
    cleanup_task: asyncio.Task[None] | None = None
    manager: mcp_client.Manager | None = None
    hook_engine: hook.Engine | None = None
    app = None
    try:
        cfg = config.load(".Licode/config.yaml")
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1

    try:
        root = os.getcwd()
        instruction_text = instructions.Loader(root).load()
        memory_manager = memory.Manager(
            str(Path(root) / ".Licode" / "memory"),
            str(Path.home() / ".Licode" / "memory"),
            provider=None,
            model="",
        )
        memory_text = memory_manager.load_index()
        runtime = SessionRuntime(
            replacement=ContentReplacementState(),
            recovery=RecoveryState(),
            auto_tracking=CompactCircuitBreaker(),
            session=new_session_context(root),
        )
        writer = session.Writer(runtime.session.session_dir)
        sessions_dir = str(Path(root) / ".Licode" / "sessions")
        cleanup_task = asyncio.create_task(
            asyncio.to_thread(
                session.clean_expired,
                sessions_dir,
                timedelta(days=30),
            )
        )
        registry = new_default_registry()
        mcp_config = mcp_client.load_config(root)
        manager = await mcp_client.new_manager(mcp_config, version=__version__)
        for external_tool in manager.tools():
            registry.register(external_tool)
        catalog = skills.Catalog.load(root)
        load_skill_tool = LoadSkillTool(catalog, runtime.active_skills)
        install_skill_tool = InstallSkillTool(catalog, Path(root))
        registry.register(load_skill_tool)
        registry.register(install_skill_tool)
        invalid_skills: set[str] = set()
        for issue in catalog.validate_tools(registry):
            print(
                f"跳过 Skill {issue.skill_name}: 未注册工具 {issue.tool_name}",
                file=sys.stderr,
            )
            invalid_skills.add(issue.skill_name)
        for skill_name in invalid_skills:
            catalog.remove(skill_name)
        engine, engine_error = permission.new_engine(root)
        if engine_error is not None:
            print(f"权限引擎降级: {engine_error}", file=sys.stderr)
        hook_engine = hook.load(root)
        subagent_catalog = subagent.load_catalog(root)
        task_mgr = task.Manager()
        for task_tool in (
            task.TaskListTool(task_mgr),
            task.TaskGetTool(task_mgr),
            task.TaskStopTool(task_mgr),
            task.SendMessageTool(task_mgr),
        ):
            registry.register(task_tool)
        agent_tool = AgentTool(
            subagent_catalog,
            task_mgr,
            parent=None,
            bg_enabled=cfg.effective_enable_subagent_background(),
        )
        registry.register(agent_tool)
        app = new_app(
            cfg.providers,
            __version__,
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
        )
        await app.run_async(inline=True, inline_no_clear=True)
        app.print_transcript()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"LiCode 启动失败: {exc}", file=sys.stderr)
        return 1
    finally:
        if app is not None:
            with suppress(Exception):
                await app.dispatch_session_end()
        if hook_engine is not None:
            with suppress(Exception):
                await hook_engine.close()
        if manager is not None:
            await manager.close()
        writer_to_close = app.writer if app is not None else writer
        if writer_to_close is not None:
            writer_to_close.close()
        if cleanup_task is not None:
            with suppress(Exception):
                await cleanup_task
    return 0


def main() -> None:
    try:
        code = asyncio.run(_amain())
    except KeyboardInterrupt:
        code = 0
    raise SystemExit(code)
