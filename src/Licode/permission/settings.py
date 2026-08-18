"""权限 YAML 配置、工具映射与调用参数提取。"""

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from Licode.llm import ToolCall

from . import Category
from .rule import RuleSet, parse_rule, with_allow


class SettingsError(Exception):
    """单个权限配置文件格式非法。"""


@dataclass
class PermissionsBlock:
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)


@dataclass
class Settings:
    default_mode: str = ""
    permissions: PermissionsBlock = field(default_factory=PermissionsBlock)


def _string_list(value: Any, name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SettingsError(f"{name} 必须是字符串列表")
    return list(value)


def load_settings(path: str) -> Settings:
    config_path = Path(path)
    if not config_path.exists():
        return Settings()
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SettingsError(f"权限配置读取失败: {path}: {exc}") from exc
    if raw is None:
        return Settings()
    if not isinstance(raw, dict):
        raise SettingsError("权限配置根节点必须是映射")
    default_mode = raw.get("default_mode", "")
    if not isinstance(default_mode, str):
        raise SettingsError("default_mode 必须是字符串")
    permissions = raw.get("permissions", {})
    if not isinstance(permissions, dict):
        raise SettingsError("permissions 必须是映射")
    return Settings(
        default_mode=default_mode,
        permissions=PermissionsBlock(
            allow=_string_list(permissions.get("allow"), "permissions.allow"),
            deny=_string_list(permissions.get("deny"), "permissions.deny"),
        ),
    )


def to_rule_set(settings: Settings) -> RuleSet:
    result = RuleSet()
    for value, allow in (
        *((item, True) for item in settings.permissions.allow),
        *((item, False) for item in settings.permissions.deny),
    ):
        rule, error = parse_rule(value)
        if rule is None:
            print(f"rule {value!r} parse failed: {error}", file=sys.stderr)
            continue
        rule = with_allow(rule, allow)
        (result.allow if allow else result.deny).append(rule)
    return result


_FRIENDLY_NAMES = {
    "bash": "Bash",
    "read_file": "Read",
    "write_file": "Write",
    "edit_file": "Edit",
    "glob": "Glob",
    "grep": "Grep",
}


def friendly_name(internal: str) -> str:
    return _FRIENDLY_NAMES.get(internal, internal)


def categorize(internal: str, read_only: bool) -> Category:
    if read_only:
        return Category.READ
    if internal in {"write_file", "edit_file"}:
        return Category.WRITE
    return Category.EXEC


def extract_target(call: ToolCall) -> tuple[str, bool, bool]:
    try:
        raw: Any = json.loads(call.input) if isinstance(call.input, str) else call.input
    except (json.JSONDecodeError, TypeError):
        return "", call.name in {"read_file", "write_file", "edit_file", "glob", "grep"}, False
    if not isinstance(raw, dict):
        return "", call.name in {"read_file", "write_file", "edit_file", "glob", "grep"}, False
    if call.name in {"read_file", "write_file", "edit_file"}:
        path = raw.get("path")
        return (path, True, True) if isinstance(path, str) and path else ("", True, False)
    if call.name in {"glob", "grep"}:
        path = raw.get("path", ".") or "."
        return (path, True, True) if isinstance(path, str) else ("", True, False)
    if call.name == "bash":
        command = raw.get("command")
        return (
            (command, False, True) if isinstance(command, str) and command else ("", False, False)
        )
    return "", False, False
