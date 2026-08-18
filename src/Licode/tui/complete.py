"""斜杠命令自动补全状态机与渲染。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rich.markup import escape
from textual import events

from Licode.command import Command, Registry

if TYPE_CHECKING:
    from .app import LiCodeApp

MAX_ROWS = 8


@dataclass(slots=True)
class CompletionMenu:
    items: list[Command] = field(default_factory=list)
    cursor: int = 0
    offset: int = 0
    active: bool = False

    def update(self, input_text: str, registry: Registry) -> None:
        if not input_text.startswith("/") or "\n" in input_text:
            self.hide()
            return
        self.items = registry.prefix_match(input_text)
        self.active = True
        self.cursor = min(self.cursor, max(0, len(self.items) - 1))
        self.offset = min(self.offset, self.cursor)
        self._ensure_cursor_visible()

    def move_up(self) -> None:
        if not self.items:
            return
        self.cursor = max(0, self.cursor - 1)
        self._ensure_cursor_visible()

    def move_down(self) -> None:
        if not self.items:
            return
        self.cursor = min(len(self.items) - 1, self.cursor + 1)
        self._ensure_cursor_visible()

    def selected(self) -> Command | None:
        if not self.items:
            return None
        return self.items[self.cursor]

    def hide(self) -> None:
        self.active = False
        self.items = []
        self.cursor = 0
        self.offset = 0

    def render(self, width: int) -> str:
        if not self.active:
            return ""
        if not self.items:
            return "[dim]无匹配[/dim]"

        width = max(8, width)
        top_more = self.offset > 0
        capacity = MAX_ROWS - int(top_more)
        bottom_more = self.offset + capacity < len(self.items)
        if bottom_more:
            capacity -= 1
        end = min(len(self.items), self.offset + capacity)
        name_width = max(len(item.name) + 1 for item in self.items[self.offset : end])
        lines: list[str] = []
        if top_more:
            lines.append(f"[dim]↑ {self.offset} more[/dim]")
        for index in range(self.offset, end):
            item = self.items[index]
            line = f"/{item.name}".ljust(name_width) + "  " + item.description
            line = escape(line[:width])
            lines.append(f"[reverse]{line}[/reverse]" if index == self.cursor else line)
        if end < len(self.items):
            lines.append(f"[dim]↓ {len(self.items) - end} more[/dim]")
        return "\n".join(lines)

    def _ensure_cursor_visible(self) -> None:
        if not self.items:
            self.offset = 0
            return
        if self.cursor < self.offset:
            self.offset = self.cursor
        while self.cursor >= self.offset + self._item_capacity():
            self.offset += 1

    def _item_capacity(self) -> int:
        top_more = self.offset > 0
        capacity = MAX_ROWS - int(top_more)
        if self.offset + capacity < len(self.items):
            capacity -= 1
        return max(1, capacity)


async def handle_completion_key(app: LiCodeApp, event: events.Key) -> bool:
    if not app.completion.active:
        return False
    if event.key == "up":
        app.completion.move_up()
    elif event.key == "down":
        app.completion.move_down()
    elif event.key == "escape":
        app.completion.hide()
    elif event.key in {"enter", "tab"}:
        selected = app.completion.selected()
        if selected is not None:
            await app._execute_selected(selected)
        elif event.key == "enter":
            await app.submit(app.input_area.text)
        else:
            app.completion.hide()
    else:
        return False
    app._render_completion()
    event.prevent_default()
    event.stop()
    return True
