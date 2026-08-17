"""TUI 中可复用的 Rich 渲染块。"""

from rich.console import Group
from rich.markdown import Markdown
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from Licode.agent import Mode


def user_block(text: str) -> Text:
    return Text("● " + text, style="bold")


def assistant_block(text: str, elapsed: float) -> Group:
    return Group(
        Text("●", style="bold cyan"),
        Markdown(text),
        Text(f"完成于 {elapsed:.1f}s", style="dim"),
    )


def error_block(error: Exception) -> Text:
    return Text("● " + str(error), style="bold red")


def notice_block(text: str) -> Text:
    return Text(text, style="dim")


def tool_line(name: str, args: str) -> Text:
    line = Text("● ", style="bold cyan")
    line.append(f"{name}({args})", style="bold")
    return line


def tool_result_summary(result: str, is_error: bool) -> Padding:
    lines = result.splitlines()
    summary = "\n".join(lines[:8])
    if len(lines) > 8:
        summary += "\n[truncated]"
    return Padding(
        Text("⎿ " + summary, style="red" if is_error else "dim"),
        (0, 0, 0, 2),
    )


def streaming_block(
    text: str,
    elapsed: float,
    iteration: int = 0,
    tools: list[tuple[str, str]] | None = None,
) -> Group:
    if tools:
        spinner = "|/-\\"[int(elapsed * 10) % 4]
        return Group(
            *(
                Text(
                    f"● {name}({args}) {spinner} Running…",
                    style="italic cyan",
                )
                for name, args in tools
            )
        )
    progress_text = f"Imagining… ({int(elapsed)}s"
    if iteration > 0:
        progress_text += f" · 第 {iteration} 轮"
    progress = Text(progress_text + ")", style="italic cyan")
    if text:
        return Group(Text("● " + text), progress)
    return Group(progress)


def _compact_tokens(value: int) -> str:
    if value < 1000:
        return str(value)
    compact = f"{value / 1000:.1f}".rstrip("0").rstrip(".")
    return compact + "k"


def status_bar(
    name: str,
    model: str,
    mode: Mode = Mode.NORMAL,
    usage_in: int = 0,
    usage_out: int = 0,
) -> Table:
    left = Text(name, style="bold")
    if mode is Mode.PLAN:
        left.append("  PLAN", style="bold yellow")
    right = Text(model, style="dim")
    right.append(
        f"  ↑{_compact_tokens(usage_in)} ↓{_compact_tokens(usage_out)} tok",
        style="dim cyan",
    )
    table = Table.grid(expand=True)
    table.add_column(justify="left", ratio=1)
    table.add_column(justify="right")
    table.add_row(left, right)
    return table
