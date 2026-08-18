"""把权限 Matcher 应用于 Hook payload 字段。"""

import json
from typing import Any

from .rule import CombineMode, Condition, Payload


def get_by_path(payload: Payload, path: str) -> str:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return ""
        current = current[part]
    if current is None:
        return ""
    if isinstance(current, str):
        return current
    if isinstance(current, (bool, int, float)):
        return str(current)
    return json.dumps(current, ensure_ascii=False, sort_keys=True)


def eval_condition(condition: Condition | None, payload: Payload) -> bool:
    if condition is None:
        return True
    matches = (atom.matcher.match(get_by_path(payload, atom.field)) for atom in condition.atoms)
    if condition.mode is CombineMode.ALL_OF:
        return all(matches)
    return any(matches)
