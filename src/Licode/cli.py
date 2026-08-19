"""LiCode 命令行入口。"""

import argparse
import asyncio
import os
import sys
from contextlib import suppress
from datetime import datetime, timedelta
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
    team,
    worktree,
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
from Licode.coordinator import is_enabled as coordinator_enabled
from Licode.team.tools import (
    SendMessageTool as TeamSendMessageTool,
)
from Licode.team.tools import (
    TaskCreateTool,
    TaskUpdateTool,
    TeamCreateTool,
    TeamDeleteTool,
)
from Licode.team.tools import TaskGetTool as TeamTaskGetTool
from Licode.team.tools import TaskListTool as TeamTaskListTool
from Licode.tool import new_default_registry
from Licode.tool.install_skill import InstallSkillTool
from Licode.tool.load_skill import LoadSkillTool
from Licode.tui import new_app


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="Licode", description="终端 AI 编程助手")
    parser.add_argument("--team-member", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--team", default="", help=argparse.SUPPRESS)
    parser.add_argument("--member", default="", help=argparse.SUPPRESS)
    parser.add_argument("--agent-id", default="", help=argparse.SUPPRESS)
    parser.add_argument("--session-dir", default="", help=argparse.SUPPRESS)
    parser.add_argument("--worktree", default="", help=argparse.SUPPRESS)
    parser.add_argument("--agent-type", default="", help=argparse.SUPPRESS)
    parser.add_argument("--model", default="", help=argparse.SUPPRESS)
    parser.add_argument("--plan-mode", action="store_true", help=argparse.SUPPRESS)
    return parser


async def _amain(args: argparse.Namespace | None = None) -> int:
    args = args or _parser().parse_args([])
    writer: session.Writer | None = None
    cleanup_task: asyncio.Task[None] | None = None
    worktree_sweep_task: asyncio.Task[list[str]] | None = None
    manager: mcp_client.Manager | None = None
    hook_engine: hook.Engine | None = None
    worktree_mgr: worktree.Manager | None = None
    app = None
    try:
        cfg = config.load(".Licode/config.yaml")
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1

    try:
        if args.team_member:
            if not args.worktree:
                raise ValueError("--team-member 需要 --worktree")
            os.chdir(args.worktree)
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
        try:
            worktree_mgr = worktree.Manager(root)
        except Exception as exc:
            print(f"Worktree 管理器降级: {exc}", file=sys.stderr)
            worktree_mgr = None
        else:
            assert worktree_mgr is not None
            worktree_sweep_task = asyncio.create_task(
                worktree_mgr.sweep_stale(datetime.now() - timedelta(hours=24))
            )
        name_registry = team.AgentNameRegistry()
        task_mgr = task.Manager(name_registry)
        team_mgr = team.Manager(Path.home(), root, worktree_mgr, task_mgr, name_registry)
        coordinator_mode = coordinator_enabled(cfg) and not args.team_member
        team_mgr.coordinator_mode = coordinator_mode
        legacy_task_list = task.TaskListTool(task_mgr)
        legacy_task_get = task.TaskGetTool(task_mgr)
        legacy_send_message = task.SendMessageTool(task_mgr)
        for task_tool in (
            TeamTaskListTool(team_mgr, legacy_task_list),
            TeamTaskGetTool(team_mgr, legacy_task_get),
            task.TaskStopTool(task_mgr),
            TeamSendMessageTool(team_mgr, legacy_send_message),
            TeamCreateTool(team_mgr),
            TeamDeleteTool(team_mgr),
            TaskCreateTool(team_mgr),
            TaskUpdateTool(team_mgr),
        ):
            registry.register(task_tool)
        agent_tool = AgentTool(
            subagent_catalog,
            task_mgr,
            parent=None,
            bg_enabled=cfg.effective_enable_subagent_background(),
            worktree_mgr=worktree_mgr,
            team_hook=team_mgr,
        )
        registry.register(agent_tool)
        team_mgr.configure_spawn(agent_tool, cfg)
        task_mgr.on_task_done(team_mgr.handle_task_done)
        if args.team_member:
            from Licode.cli_team_member import run_team_member

            return await run_team_member(
                args,
                cfg,
                registry,
                engine,
                hook_engine,
                team_mgr,
                subagent_catalog,
                agent_tool,
            )
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
            worktree_mgr,
            team_mgr,
            coordinator_mode,
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
        if worktree_sweep_task is not None:
            with suppress(Exception):
                await worktree_sweep_task
    return 0


def main() -> None:
    args = _parser().parse_args()
    try:
        code = asyncio.run(_amain(args))
    except KeyboardInterrupt:
        code = 0
    raise SystemExit(code)
