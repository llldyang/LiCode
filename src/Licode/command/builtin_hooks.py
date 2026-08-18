"""Hook 列表命令。"""

from Licode.hook import Event
from Licode.hook.rule import Rule

from .ui import UI


async def handle_hooks(ui: UI) -> None:
    rules = ui.hook_rules()
    if not rules:
        ui.println("No hooks loaded.")
        return
    lines: list[str] = []
    groups: dict[Event, list[Rule]] = {}
    for rule in rules:
        groups.setdefault(rule.event, []).append(rule)
    for event, event_rules in groups.items():
        lines.append(f"{event.value}:")
        for rule in event_rules:
            flags = " ".join(
                flag
                for enabled, flag in (
                    (rule.only_once, "[once]"),
                    (rule.asyncio_mode, "[async]"),
                )
                if enabled
            )
            suffix = f"  {flags}" if flags else ""
            lines.append(f"  {rule.name}  {rule.event.value}  {rule.action.type.value}{suffix}")
    sources = ui.hook_sources()
    lines.append(f"Loaded from: {', '.join(sources)}")
    ui.println("\n".join(lines))
