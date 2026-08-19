"""Coordinator Mode 的双锁、工具白名单与系统提示词。"""

import os
from typing import Any

COORDINATOR_ALLOWED_TOOLS: list[str] = [
    "Agent",
    "TeamCreate",
    "TeamDelete",
    "TaskCreate",
    "TaskGet",
    "TaskList",
    "TaskUpdate",
    "SendMessage",
    "read_file",
    "glob",
    "grep",
    "bash",
]

SYSTEM_PROMPT_SUFFIX = """

你当前处于 Coordinator Mode。按 Research、Synthesis、Implementation、Verification
四个阶段组织团队工作，并把实际修改委派给队员。

派出 Agent 或通过 SendMessage 分配任务后，必须停手等待汇报：不要立刻调用
read_file、glob、grep 或 bash 自己重复探索，也不要用 sleep 或 TaskList 轮询凑时间。
此时只需用一行说明已经派出多少名队员、正在等待什么结果，然后结束当前轮。

你只能在 Research 阶段首次定位目标、Synthesis 阶段读取队员产出的报告文件，或
Verification 阶段执行 git diff、git status、测试与合并时自行使用读类工具和 bash。
收敛时逐个合并队员分支；冲突无法可靠解决时执行 git merge --abort，保留对应
Worktree，并把冲突文件和路径报告给用户。
""".strip()


def env_truthy(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes"}


def is_enabled(config: Any) -> bool:
    features = getattr(config, "features", None)
    if not bool(getattr(features, "coordinator_mode", False)):
        return False
    return env_truthy(os.environ.get("MEWCODE_COORDINATOR_MODE", "")) or env_truthy(
        os.environ.get("LICODE_COORDINATOR_MODE", "")
    )


def allowed_tools() -> list[str]:
    return list(COORDINATOR_ALLOWED_TOOLS)


def system_prompt_suffix() -> str:
    return SYSTEM_PROMPT_SUFFIX


__all__ = [
    "COORDINATOR_ALLOWED_TOOLS",
    "allowed_tools",
    "env_truthy",
    "is_enabled",
    "system_prompt_suffix",
]
