from Licode.command import NopUI, Registry, register_builtins
from Licode.permission import Mode


class RecordingUI(NopUI):
    def __init__(self, *, is_idle: bool = True) -> None:
        self.printed: list[str] = []
        self.errors: list[str] = []
        self.modes: list[Mode] = []
        self.injections: list[tuple[str, str]] = []
        self.compact_calls = 0
        self.is_idle = is_idle

    def println(self, msg: str) -> None:
        self.printed.append(msg)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def set_mode(self, mode: Mode) -> None:
        self.modes.append(mode)

    def inject_and_send(self, display_label: str, preset_prompt: str) -> None:
        self.injections.append((display_label, preset_prompt))

    def force_compact(self) -> None:
        self.compact_calls += 1

    def memory_files(self) -> list[str]:
        return ["MEMORY.md"]

    def idle(self) -> bool:
        return self.is_idle


def builtins() -> Registry:
    registry = Registry()
    register_builtins(registry)
    return registry


def test_register_builtins_all_registered() -> None:
    names = [item.name for item in builtins().visible()]

    assert names == [
        "clear",
        "compact",
        "do",
        "exit",
        "help",
        "memory",
        "permission",
        "plan",
        "resume",
        "review",
        "session",
        "status",
    ]


def test_register_builtins_no_collision() -> None:
    register_builtins(Registry())


async def test_register_builtins_handlers_run_on_nop_ui() -> None:
    for command in builtins().visible():
        await command.handler(NopUI())


async def test_handle_status_prints_all_keys() -> None:
    ui = RecordingUI()
    command = builtins().lookup("status")
    assert command is not None

    await command.handler(ui)

    assert len(ui.printed) == 1
    for key in ("Mode:", "Tokens:", "Tools:", "Memories:", "Model:", "Directory:"):
        assert key in ui.printed[0]


async def test_handle_compact_blocks_when_busy() -> None:
    ui = RecordingUI(is_idle=False)
    command = builtins().lookup("compact")
    assert command is not None

    await command.handler(ui)

    assert ui.errors == ["请等待当前任务完成"]
    assert ui.compact_calls == 0


async def test_handle_do_sets_mode_and_injects() -> None:
    ui = RecordingUI()
    command = builtins().lookup("do")
    assert command is not None

    await command.handler(ui)

    assert ui.modes == [Mode.DEFAULT]
    assert ui.injections and ui.injections[0][0] == "/do"
    assert "开始执行" in ui.injections[0][1]


async def test_help_prints_twelve_sorted_commands() -> None:
    ui = RecordingUI()
    command = builtins().lookup("help")
    assert command is not None

    await command.handler(ui)

    lines = ui.printed[0].splitlines()
    assert len(lines) == 12
    assert [line.split()[0] for line in lines] == [f"/{item.name}" for item in builtins().visible()]
