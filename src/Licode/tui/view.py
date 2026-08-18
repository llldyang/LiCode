"""TUI 中可复用的 Rich 渲染块。"""

from rich.console import Group
from rich.markdown import Markdown
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from Licode.agent import ApprovalRequest, CompactEvent, CompactPhase
from Licode.permission import Mode


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


def format_compact_notice(event: CompactEvent) -> str:
    if event.phase is CompactPhase.BEFORE_AUTO:
        return "正在压缩上下文..."
    if event.phase is CompactPhase.BEFORE_EMERGENCY:
        return "上下文撞墙，自动压缩中..."
    if event.err is not None:
        return f"压缩失败：{event.err}"
    return f"已压缩，token 从 {event.before} 降至 {event.after}"


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


def approval_block(request: ApprovalRequest, cursor: int) -> Group:
    """渲染人在回路的三选一待批准块。"""

    lines: list[Text] = [Text(f"● {request.name}", style="bold cyan")]
    lines.append(Text("  " + request.args))
    lines.append(Text("  " + request.reason, style="dim"))
    lines.append(Text("是否继续?", style="bold"))
    choices = ("1. 允许本次", "2. 永久允许（写入本地配置）", "3. 拒绝本次")
    for index, choice in enumerate(choices):
        prefix = "> " if index == cursor else "  "
        style = "bold cyan" if index == cursor else ""
        lines.append(Text(prefix + choice, style=style))
    lines.append(Text("↑↓ 选择 · 回车确认 · Esc 取消", style="dim"))
    return Group(*lines)


def _compact_tokens(value: int) -> str:
    if value < 1000:
        return str(value)
    compact = f"{value / 1000:.1f}".rstrip("0").rstrip(".")
    return compact + "k"


def status_bar(
    mode: Mode,
    model: str,
    usage_in: int = 0,
    usage_out: int = 0,
) -> Table:
    labels = {
        Mode.DEFAULT: ("DEFAULT", "bold green"),
        Mode.ACCEPT_EDITS: ("ACCEPT EDITS", "bold cyan"),
        Mode.PLAN: ("PLAN", "bold yellow"),
        Mode.BYPASS: ("BYPASS", "bold red"),
    }
    label, style = labels[mode]
    left = Text(label, style=style)
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
