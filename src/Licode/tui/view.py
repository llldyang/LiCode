"""TUI 中可复用的 Rich 渲染块。"""

from rich.console import Group
from rich.markdown import Markdown
from rich.table import Table
from rich.text import Text


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


def streaming_block(text: str, elapsed: float) -> Group:
    progress = Text(f"Imagining… ({int(elapsed)}s)", style="italic cyan")
    if text:
        return Group(Text("● " + text), progress)
    return Group(progress)


def status_bar(name: str, model: str) -> Table:
    table = Table.grid(expand=True)
    table.add_column(justify="left", ratio=1)
    table.add_column(justify="right")
    table.add_row(Text(name, style="bold"), Text(model, style="dim"))
    return table
