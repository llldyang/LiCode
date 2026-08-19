"""Hook YAML 双层加载与集中校验。"""

from __future__ import annotations

import re
import sys
from math import isfinite
from pathlib import Path
from typing import Any

import yaml

from Licode.permission.matcher import Matcher, compile_matcher

from .engine import Engine
from .event import is_blocking, parse_event
from .rule import (
    Action,
    ActionType,
    AtomCondition,
    CombineMode,
    Condition,
    HttpAction,
    PromptAction,
    Rule,
    ShellAction,
    SubagentAction,
)

PROJECT_HOOKS_PATH = Path(".LiCode") / "hooks.yaml"
USER_HOOKS_PATH = Path(".LiCode") / "hooks.yaml"
_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)([smh]?)$")


def load(project_root: str | Path) -> Engine:
    """按项目级、用户级顺序加载，错误只写 stderr。"""

    candidates = [
        Path(project_root).resolve() / PROJECT_HOOKS_PATH,
        Path.home() / USER_HOOKS_PATH,
    ]
    rules: list[Rule] = []
    sources: list[str] = []
    names: set[str] = set()
    for path in candidates:
        if not path.is_file():
            continue
        parsed = _read_file(path)
        if parsed is None:
            continue
        sources.append(str(path))
        for index, raw in enumerate(parsed, start=1):
            rule = _compile_rule(path, index, raw)
            if rule is None:
                continue
            if rule.name in names:
                print(f'hook "{rule.name}": duplicate name, skipped', file=sys.stderr)
                continue
            names.add(rule.name)
            rules.append(rule)
    return Engine(rules, sources)


def _read_file(path: Path) -> list[Any] | None:
    try:
        root = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        print(f"hooks file {path} load failed: {exc}", file=sys.stderr)
        return None
    if not isinstance(root, dict) or not isinstance(root.get("hooks"), list):
        print(f"hooks file {path} load failed: root hooks must be a list", file=sys.stderr)
        return None
    return root["hooks"]


def _compile_rule(path: Path, index: int, raw: Any) -> Rule | None:
    if not isinstance(raw, dict):
        _rule_error(f"#{index}", "rule must be an object")
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        _rule_error(f"#{index}", "name is required")
        return None
    name = name.strip()
    event_value = raw.get("event")
    event = parse_event(event_value) if isinstance(event_value, str) else None
    if event is None:
        _rule_error(name, f'unknown event "{event_value}"')
        return None
    try:
        condition = _compile_condition(raw.get("if"))
        action = _compile_action(raw.get("action"))
        only_once = _bool_field(raw, "only_once", False)
        asyncio_mode = _bool_field(raw, "async", False)
        timeout_s = _parse_duration(raw.get("timeout", "30s"))
    except ValueError as exc:
        _rule_error(name, str(exc))
        return None
    if asyncio_mode and is_blocking(event):
        _rule_error(name, "async not allowed for blocking events")
        return None
    return Rule(
        name=name,
        event=event,
        action=action,
        condition=condition,
        only_once=only_once,
        asyncio_mode=asyncio_mode,
        timeout_s=timeout_s,
        source=str(path),
    )


def _compile_condition(raw: Any) -> Condition | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("if must be an object")
    present = [key for key in ("all_of", "any_of") if key in raw]
    if len(present) != 1 or len(raw) != 1:
        raise ValueError("if must contain exactly one of all_of or any_of")
    key = present[0]
    atoms_raw = raw[key]
    if not isinstance(atoms_raw, list):
        raise ValueError(f"if.{key} must be a list")
    atoms: list[AtomCondition] = []
    for atom_raw in atoms_raw:
        if not isinstance(atom_raw, dict):
            raise ValueError("condition atom must be an object")
        field = atom_raw.get("field")
        if not isinstance(field, str) or not field:
            raise ValueError("condition field is required")
        atoms.append(AtomCondition(field, _compile_structured_matcher(atom_raw.get("match"))))
    return Condition(CombineMode(key), atoms)


def _compile_structured_matcher(raw: Any) -> Matcher:
    if not isinstance(raw, dict):
        raise ValueError("condition match must be an object")
    matcher_type = raw.get("type")
    if matcher_type == "not":
        if "inner" not in raw:
            raise ValueError("not matcher requires inner")
        from Licode.permission.matcher import NotMatcher

        return NotMatcher(_compile_structured_matcher(raw["inner"]))
    value = raw.get("value")
    if matcher_type not in {"exact", "glob", "regex"}:
        raise ValueError(f"unknown matcher type: {matcher_type}")
    if not isinstance(value, str):
        raise ValueError(f"{matcher_type} matcher requires string value")
    prefix = {"exact": "=", "glob": "", "regex": "~"}[matcher_type]
    return compile_matcher(prefix + value, is_command=False)


def _compile_action(raw: Any) -> Action:
    if not isinstance(raw, dict):
        raise ValueError("action must be an object")
    action_value = raw.get("type")
    if not isinstance(action_value, str):
        raise ValueError(f"unknown action type: {action_value}")
    try:
        action_type = ActionType(action_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unknown action type: {action_value}") from exc
    if action_type is ActionType.SHELL:
        command = _required_string(raw, "command", "shell action")
        return Action(action_type, shell=ShellAction(command))
    if action_type is ActionType.PROMPT:
        text = _required_string(raw, "text", "prompt action")
        return Action(action_type, prompt=PromptAction(text))
    if action_type is ActionType.HTTP:
        url = _required_string(raw, "url", "http action")
        method = raw.get("method", "POST")
        headers = raw.get("headers", {})
        body = raw.get("body")
        if not isinstance(method, str) or not method:
            raise ValueError("http action method must be a string")
        if not isinstance(headers, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in headers.items()
        ):
            raise ValueError("http action headers must be string pairs")
        if body is not None and not isinstance(body, str):
            raise ValueError("http action body must be a string")
        return Action(
            action_type,
            http=HttpAction(url, method.upper(), dict(headers), body),
        )
    agent_name = _required_string(raw, "agent_name", "subagent action")
    prompt = _required_string(raw, "prompt", "subagent action")
    return Action(action_type, subagent=SubagentAction(agent_name, prompt))


def _required_string(raw: dict[str, Any], key: str, owner: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{owner} requires {key}")
    return value


def _bool_field(raw: dict[str, Any], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _parse_duration(raw: Any) -> float:
    if isinstance(raw, bool):
        raise ValueError("timeout must be a duration")
    if isinstance(raw, (int, float)):
        seconds = float(raw)
    elif isinstance(raw, str):
        match = _DURATION_RE.fullmatch(raw.strip())
        if match is None:
            raise ValueError("timeout must be a duration such as 30s")
        seconds = float(match.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[match.group(2)]
    else:
        raise ValueError("timeout must be a duration")
    if not isfinite(seconds) or seconds <= 0:
        raise ValueError("timeout must be greater than zero")
    return seconds


def _rule_error(name: str, reason: str) -> None:
    print(f'hook "{name}": {reason}, skipped', file=sys.stderr)
