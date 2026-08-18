"""只读取本地状态的内置命令。"""

from .command import Handler
from .registry import Registry
from .ui import UI


def make_help_handler(registry: Registry) -> Handler:
    async def handle_help(ui: UI) -> None:
        commands = registry.visible()
        width = max((len(cmd.name) for cmd in commands), default=0)
        ui.println("\n".join(f"/{cmd.name.ljust(width)}  {cmd.description}" for cmd in commands))

    return handle_help


async def handle_status(ui: UI) -> None:
    values = (
        ("Mode:", str(ui.mode())),
        ("Tokens:", f"{ui.usage_in()} in / {ui.usage_out()} out"),
        ("Tools:", f"{ui.tool_count()} enabled"),
        ("Memories:", f"{len(ui.memory_files())} files"),
        ("Model:", ui.model_name()),
        ("Directory:", ui.cwd()),
    )
    width = max(len(key) for key, _ in values)
    lines = ["LiCode Status", ""]
    lines.extend(f"{key.ljust(width)} {value}" for key, value in values)
    ui.println("\n".join(lines))


async def handle_memory(ui: UI) -> None:
    files = ui.memory_files()
    ui.println("\n".join(files) if files else "无已加载的记忆文件")


async def handle_permission(ui: UI) -> None:
    ui.println(str(ui.mode()))


async def handle_session(ui: UI) -> None:
    ui.println(f"Session: {ui.session_id()}\nPath: {ui.session_path()}")
