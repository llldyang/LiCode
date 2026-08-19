import pytest

from Licode.command import Kind, NopUI, Registry, WorktreeSummary, register_builtins
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


class StubWorktreeAccessor:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.summaries = [WorktreeSummary("demo", "C:/repo/demo", "worktree-demo", False, True)]

    async def create(self, name: str) -> tuple[str, str]:
        self.calls.append(("create", name))
        return "C:/repo/demo", "worktree-demo"

    def list(self) -> list[WorktreeSummary]:
        self.calls.append(("list",))
        return self.summaries

    async def enter(self, name: str) -> None:
        self.calls.append(("enter", name))
        self.summaries[0].active = True

    async def exit(self, action: str, discard: bool) -> bool:
        self.calls.append(("exit", action, discard))
        return action == "remove"

    async def remove(self, name: str, discard: bool) -> None:
        self.calls.append(("remove", name, discard))


class WorktreeUI(RecordingUI):
    def __init__(self) -> None:
        super().__init__()
        self.accessor = StubWorktreeAccessor()

    def worktree_accessor(self) -> StubWorktreeAccessor:
        return self.accessor


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
        "hooks",
        "memory",
        "permission",
        "plan",
        "resume",
        "review",
        "session",
        "skill",
        "status",
        "worktree",
    ]


def test_original_twelve_commands_keep_their_execution_kinds() -> None:
    expected = {
        "clear": Kind.UI,
        "compact": Kind.UI,
        "do": Kind.PROMPT,
        "exit": Kind.UI,
        "help": Kind.LOCAL,
        "memory": Kind.LOCAL,
        "permission": Kind.LOCAL,
        "plan": Kind.UI,
        "resume": Kind.UI,
        "review": Kind.PROMPT,
        "session": Kind.LOCAL,
        "status": Kind.LOCAL,
    }
    registry = builtins()
    actual: dict[str, Kind] = {}
    for name in expected:
        command = registry.lookup(name)
        assert command is not None
        assert not command.hidden
        actual[name] = command.kind

    assert actual == expected


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


async def test_help_prints_fourteen_sorted_commands() -> None:
    ui = RecordingUI()
    command = builtins().lookup("help")
    assert command is not None

    await command.handler(ui)

    lines = ui.printed[0].splitlines()
    assert len(lines) == 15
    assert [line.split()[0] for line in lines] == [f"/{item.name}" for item in builtins().visible()]


async def test_handle_worktree_all_subcommands() -> None:
    ui = WorktreeUI()
    command = builtins().lookup("worktree")
    assert command is not None and command.args_handler is not None

    for args in (
        "create demo",
        "list",
        "enter demo",
        "exit --remove --discard",
        "remove demo --discard",
    ):
        await command.args_handler(ui, args)

    assert ("create", "demo") in ui.accessor.calls
    assert ("enter", "demo") in ui.accessor.calls
    assert ("exit", "remove", True) in ui.accessor.calls
    assert ("remove", "demo", True) in ui.accessor.calls
    assert any("[手动]" in line for line in ui.printed)


async def test_handle_worktree_reports_unavailable() -> None:
    command = builtins().lookup("worktree")
    assert command is not None and command.args_handler is not None
    with pytest.raises(RuntimeError, match="不可用"):
        await command.args_handler(NopUI(), "list")
