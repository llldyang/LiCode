"""斜杠命令注册中心。"""

from collections.abc import Callable

from .command import Command


class Registry:
    """集中注册、查找并列出斜杠命令。"""

    def __init__(self) -> None:
        self._by_name: dict[str, Command] = {}
        self._visible: list[Command] = []

    def register(self, cmd: Command) -> None:
        keys = (cmd.name, *cmd.aliases)
        seen: set[str] = set()
        for key in keys:
            if not key or key != key.lower():
                raise ValueError(f"命令名必须是非空小写字符串: {key}")
            if key in seen or key in self._by_name:
                raise RuntimeError(f"command conflict: {key}")
            seen.add(key)

        for key in keys:
            self._by_name[key] = cmd
        if not cmd.hidden:
            self._visible.append(cmd)
            self._visible.sort(key=lambda item: item.name)

    def lookup(self, name: str) -> Command | None:
        return self._by_name.get(name.lower())

    def visible(self) -> list[Command]:
        return list(self._visible)

    def prefix_match(self, prefix: str) -> list[Command]:
        normalized = prefix.lstrip("/").lower()
        return [cmd for cmd in self._visible if cmd.name.startswith(normalized)]

    def remove_all(self, predicate: Callable[[Command], bool]) -> None:
        removed = {id(command) for command in self._visible if predicate(command)}
        if not removed:
            return
        self._visible = [command for command in self._visible if id(command) not in removed]
        self._by_name = {
            key: command for key, command in self._by_name.items() if id(command) not in removed
        }
