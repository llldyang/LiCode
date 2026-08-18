"""LiCode 内置斜杠命令清单。"""

from .builtin_hooks import handle_hooks
from .builtin_local import (
    handle_memory,
    handle_permission,
    handle_session,
    handle_status,
    make_help_handler,
)
from .builtin_prompt import handle_do, handle_review
from .builtin_skill import handle_skill
from .builtin_ui import handle_clear, handle_compact, handle_exit, handle_plan, handle_resume
from .builtin_worktree import handle_worktree, handle_worktree_root
from .command import Command, Kind
from .registry import Registry


def register_builtins(registry: Registry) -> None:
    """一次性注册全部内置命令。"""

    commands = (
        Command("clear", "清空当前对话并开启新会话", Kind.UI, handle_clear),
        Command("compact", "立即压缩当前上下文", Kind.UI, handle_compact),
        Command("do", "退出计划模式并开始执行", Kind.PROMPT, handle_do),
        Command("exit", "退出 LiCode", Kind.UI, handle_exit),
        Command("help", "列出所有可用命令", Kind.LOCAL, make_help_handler(registry)),
        Command("hooks", "列出已加载的 Hook", Kind.LOCAL, handle_hooks),
        Command("memory", "列出已加载的记忆文件", Kind.LOCAL, handle_memory),
        Command("permission", "显示当前权限模式", Kind.LOCAL, handle_permission),
        Command("plan", "进入计划模式", Kind.UI, handle_plan),
        Command("resume", "恢复历史会话", Kind.UI, handle_resume),
        Command("review", "请求 AI 审查当前代码", Kind.PROMPT, handle_review),
        Command("session", "显示当前会话信息", Kind.LOCAL, handle_session),
        Command("skill", "列出已加载的 Skill", Kind.LOCAL, handle_skill),
        Command("status", "显示 LiCode 运行状态", Kind.LOCAL, handle_status),
        Command(
            "worktree",
            "管理 Git Worktree 隔离目录",
            Kind.LOCAL,
            handle_worktree_root,
            args_handler=handle_worktree,
        ),
    )
    for command in commands:
        registry.register(command)
