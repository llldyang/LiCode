"""动态补充指令与规划模式提醒。"""

EXECUTE_DIRECTIVE = "请按上面的计划开始执行。"

_PLAN_REMINDER_FULL = (
    "You are in PLAN MODE. Use only read-only tools to investigate the codebase. "
    "Do not write or edit files and do not run shell commands. Produce a clear, "
    "step-by-step plan, then stop and wait for the user to approve it with /do. "
    "Do not reply to or repeat this reminder; follow it as system context."
)

_PLAN_REMINDER_CONCISE = (
    "PLAN MODE remains active. Continue with read-only investigation and wait for /do "
    "before making changes. Do not reply to this reminder."
)


def system_reminder(body: str) -> str:
    """用专用标签包裹一段不应被直接回复的补充指令。"""

    return f"<system-reminder>\n{body}\n</system-reminder>"


def plan_reminder(full: bool) -> str:
    """构造完整或精简的规划模式提醒。"""

    body = _PLAN_REMINDER_FULL if full else _PLAN_REMINDER_CONCISE
    return system_reminder(body)
