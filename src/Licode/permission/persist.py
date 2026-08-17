"""人在回路永久放行的精确本地规则写入。"""

from pathlib import Path
from typing import Any, Protocol

import yaml

from Licode.llm import ToolCall

from .rule import Rule, RuleSet, escape_glob
from .sandbox import project_relative
from .settings import extract_target, friendly_name, load_settings


class PersistableEngine(Protocol):
    root: str
    local_path: str
    local: RuleSet


def rule_for(engine: PersistableEngine, call: ToolCall) -> tuple[Rule, str, bool]:
    target, is_file, ok = extract_target(call)
    friendly = friendly_name(call.name)
    if not ok:
        if not call.name or friendly != call.name:
            return Rule("", "", False), "", False
        rule = Rule(friendly, "", True)
        return rule, rule.render(), True
    if not target:
        return Rule("", "", False), "", False
    try:
        exact_target = project_relative(engine.root, target) if is_file else target
    except (OSError, ValueError):
        return Rule("", "", False), "", False
    exact_pattern = escape_glob(exact_target)
    rule = Rule(friendly, exact_pattern, True)
    return rule, rule.render(), True


def persist_local_allow(engine: PersistableEngine, call: ToolCall) -> None:
    """把本次调用转换为精确 allow 规则并写入本地层。"""

    rule, rendered, ok = rule_for(engine, call)
    if not ok:
        raise ValueError("无法为该工具调用生成永久规则")
    settings = load_settings(engine.local_path)
    if rendered not in settings.permissions.allow:
        settings.permissions.allow.append(rendered)
    data: dict[str, Any] = {
        "permissions": {
            "allow": settings.permissions.allow,
            "deny": settings.permissions.deny,
        }
    }
    if settings.default_mode:
        data = {"default_mode": settings.default_mode, **data}
    path = Path(engine.local_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    local = getattr(engine, "local")
    if not any(existing.render() == rendered for existing in local.allow):
        local.allow.append(rule)
