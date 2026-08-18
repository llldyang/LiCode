"""Worktree 斜杠命令。"""

from .ui import UI

USAGE = (
    "用法: /worktree create <名称> | list | enter <名称> | "
    "exit [--remove] [--discard] | remove <名称> [--discard]"
)


def _require_no_extra(parts: list[str], expected: int) -> None:
    if len(parts) != expected:
        raise ValueError(USAGE)


async def handle_worktree_root(ui: UI) -> None:
    """兼容无参数 Command handler；实际分发使用 args_handler。"""

    ui.error(USAGE)


async def handle_worktree(ui: UI, args: str) -> None:
    """解析并执行 Worktree 子命令。"""

    accessor = ui.worktree_accessor()
    if accessor is None:
        raise RuntimeError("Worktree 功能不可用")
    parts = args.split()
    if not parts:
        raise ValueError(USAGE)

    subcommand = parts[0].lower()
    if subcommand == "create":
        _require_no_extra(parts, 2)
        path, branch = await accessor.create(parts[1])
        ui.println(f"Worktree 已创建: {path} (分支 {branch})")
        return
    if subcommand == "list":
        _require_no_extra(parts, 1)
        summaries = accessor.list()
        if not summaries:
            ui.println("暂无 Worktree")
            return
        for item in summaries:
            tags = []
            if item.active:
                tags.append("active")
            if item.manual:
                tags.append("manual")
            suffix = " ".join(f"[{tag}]" for tag in tags)
            ui.println(f"{item.name}  {item.path}  {item.branch}  {suffix}".rstrip())
        return
    if subcommand == "enter":
        _require_no_extra(parts, 2)
        await accessor.enter(parts[1])
        selected = next((item for item in accessor.list() if item.name == parts[1]), None)
        path = selected.path if selected is not None else parts[1]
        ui.println(f"已进入 {parts[1]}: {path}")
        return
    if subcommand == "exit":
        allowed = {"--remove", "--discard"}
        option_flags = set(parts[1:])
        if len(option_flags) != len(parts[1:]) or not option_flags <= allowed:
            raise ValueError(USAGE)
        removed = await accessor.exit(
            "remove" if "--remove" in option_flags else "keep",
            "--discard" in option_flags,
        )
        ui.println("已退出并删除 Worktree" if removed else "已退出 Worktree")
        return
    if subcommand == "remove":
        if len(parts) not in {2, 3} or (len(parts) == 3 and parts[2] != "--discard"):
            raise ValueError(USAGE)
        await accessor.remove(parts[1], "--discard" in parts[2:])
        ui.println(f"Worktree 已删除: {parts[1]}")
        return
    raise ValueError(f"未知 Worktree 子命令: {subcommand}。{USAGE}")
