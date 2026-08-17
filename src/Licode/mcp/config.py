"""MCP server 两层配置加载、变量展开与校验。"""

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml


@dataclass
class ServerConfig:
    """已展开环境变量并完成校验的单个 MCP server 配置。"""

    type: Literal["stdio", "http"]
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    """合并后的 MCP server 配置。"""

    servers: dict[str, ServerConfig] = field(default_factory=dict)


@dataclass
class _RawServer:
    type: Any = None
    command: Any = ""
    args: Any = field(default_factory=list)
    env: Any = field(default_factory=dict)
    url: Any = ""
    headers: Any = field(default_factory=dict)


_ENV_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _warn(message: str) -> None:
    print(f"[mcp] warn: {message}", file=sys.stderr)


def _load_file(path: Path) -> dict[str, _RawServer]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ValueError("configuration root must be a mapping")
        raw_servers = data.get("mcp_servers") or {}
        if not isinstance(raw_servers, dict):
            raise ValueError("mcp_servers must be a mapping")
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        _warn(f"load {path} failed: {exc}")
        return {}

    servers: dict[str, _RawServer] = {}
    for name, raw in raw_servers.items():
        if not isinstance(name, str) or not isinstance(raw, dict):
            _warn(f"skip server {name}: definition must be a named mapping")
            continue
        servers[name] = _RawServer(
            type=raw.get("type"),
            command=raw.get("command", ""),
            args=raw.get("args", []),
            env=raw.get("env", {}),
            url=raw.get("url", ""),
            headers=raw.get("headers", {}),
        )
    return servers


def _expand_vars(value: str) -> tuple[str, list[str]]:
    undefined: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in os.environ:
            undefined.append(name)
        return os.environ.get(name, "")

    return _ENV_VAR.sub(replace, value), undefined


def _apply_expansion(name: str, server: _RawServer) -> None:
    undefined: set[str] = set()
    for field_name in ("env", "headers"):
        values = getattr(server, field_name)
        if not isinstance(values, dict):
            continue
        expanded: dict[object, object] = {}
        for key, value in values.items():
            if isinstance(value, str):
                value, missing = _expand_vars(value)
                undefined.update(missing)
            expanded[key] = value
        setattr(server, field_name, expanded)
    for variable in sorted(undefined):
        _warn(f"undefined env var ${{{variable}}} referenced by server {name}")


def _merge_servers(
    user: dict[str, _RawServer], project: dict[str, _RawServer]
) -> dict[str, _RawServer]:
    merged = dict(user)
    merged.update(project)
    return merged


def _string_map(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        return None
    return dict(value)


def _validate_server(name: str, server: _RawServer) -> ServerConfig | None:
    if server.type not in {"stdio", "http"}:
        _warn(f"skip server {name}: type must be stdio or http")
        return None
    if server.type == "stdio" and (not isinstance(server.command, str) or not server.command):
        _warn(f"skip server {name}: stdio command is required")
        return None
    if server.type == "http" and (not isinstance(server.url, str) or not server.url):
        _warn(f"skip server {name}: http url is required")
        return None
    if not isinstance(server.args, list) or not all(isinstance(arg, str) for arg in server.args):
        _warn(f"skip server {name}: args must be a string list")
        return None
    env = _string_map(server.env)
    if env is None:
        _warn(f"skip server {name}: env must be a string mapping")
        return None
    headers = _string_map(server.headers)
    if headers is None:
        _warn(f"skip server {name}: headers must be a string mapping")
        return None
    return ServerConfig(
        type=server.type,
        command=server.command if isinstance(server.command, str) else "",
        args=list(server.args),
        env=env,
        url=server.url if isinstance(server.url, str) else "",
        headers=headers,
    )


def load_config(root: str) -> Config:
    """加载用户级与项目级配置；所有配置错误均降级为空层或跳过单项。"""

    user: dict[str, _RawServer] = {}
    try:
        user = _load_file(Path.home() / ".Licode" / "config.yaml")
    except Exception as exc:
        _warn(f"load user config failed: {exc}")

    project: dict[str, _RawServer] = {}
    try:
        project = _load_file(Path(root) / ".Licode.yaml")
    except Exception as exc:
        _warn(f"load project config failed: {exc}")

    for name, server in user.items():
        _apply_expansion(name, server)
    for name, server in project.items():
        _apply_expansion(name, server)

    servers: dict[str, ServerConfig] = {}
    for name, raw in _merge_servers(user, project).items():
        validated = _validate_server(name, raw)
        if validated is not None:
            servers[name] = validated
    return Config(servers)
