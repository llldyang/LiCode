"""在独立 Git Worktree 中执行 SubAgent。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from Licode.tool import with_cwd
from Licode.worktree import Manager, random_agent_name

if TYPE_CHECKING:
    import asyncio

    from Licode.conversation import Conversation

    from . import Agent, AgentOutput


def build_worktree_notice(parent_cwd: str, wt_path: str) -> str:
    """构造隔离目录说明，避免 SubAgent 混淆父目录和副本。"""

    return (
        "<worktree-context>\n"
        "你当前在一个独立的 Git Worktree 副本中工作，与父 Agent 隔离。\n"
        f"- 父目录: {parent_cwd}\n"
        f"- 你的工作目录: {wt_path}\n"
        "- 父 Agent 提到的绝对路径基于父目录，你需要翻译成本地路径（替换前缀）再读写\n"
        "- 编辑文件前，必须先在本地 Worktree 重新 read_file 一次，避免使用过时内容\n"
        "</worktree-context>"
    )


async def execute_with_worktree(
    manager: Manager,
    definition: Any,
    sub_agent: Agent,
    sub_conv: Conversation,
    prompt: str,
    events: asyncio.Queue[AgentOutput | None],
) -> str:
    """创建临时 Worktree，在其 cwd 中执行并按变更状态清理。"""

    del definition
    name = random_agent_name()
    worktree = await manager.create(name, "HEAD", manual=False)
    parent_cwd = str(Path.cwd())
    notice = build_worktree_notice(parent_cwd, worktree.path)
    task_text = f"{notice}\n\n{prompt}"
    try:
        with with_cwd(worktree.path):
            final_text = await sub_agent.run_to_completion(sub_conv, task_text, events)
    except BaseException:
        await manager.auto_cleanup(name)
        raise
    report = await manager.auto_cleanup(name)
    if report.kept:
        final_text += f"\n[Worktree 保留在 {report.path}，分支 {report.branch}]"
    return final_text


_execute_with_worktree = execute_with_worktree

__all__ = ["_execute_with_worktree", "build_worktree_notice", "execute_with_worktree"]
