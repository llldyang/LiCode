"""解析 SubAgent 的 Markdown 与 YAML frontmatter。"""

import re
import sys
from pathlib import Path
from typing import Any, cast

import yaml

from Licode.permission import Mode, parse_mode

from .definition import Definition, Source

UTF8_BOM = b"\xef\xbb\xbf"
AGENT_NAME_REGEX = re.compile(r"^[A-Za-z][A-Za-z0-9\-_]{0,31}$")
VALID_MODELS = {"inherit", "haiku", "sonnet", "opus"}
VALID_ISOLATIONS = {"", "worktree"}


def parse_frontmatter_and_body(data: bytes) -> tuple[dict[str, Any], str]:
    """拆分 UTF-8 Markdown 的 frontmatter 与正文。"""

    if data.startswith(UTF8_BOM):
        data = data[len(UTF8_BOM) :]
    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"Agent 定义不是有效 UTF-8: {exc}") from exc
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("缺少开头 frontmatter 分隔符 ---")
    try:
        closing = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError("frontmatter 未闭合") from exc
    try:
        loaded = yaml.safe_load("\n".join(lines[1:closing]))
    except yaml.YAMLError as exc:
        raise ValueError(f"frontmatter YAML 无效: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError("frontmatter 必须是 YAML 映射")
    body = "\n".join(lines[closing + 1 :]).lstrip("\n")
    return cast(dict[str, Any], loaded), body


def _string_list(frontmatter: dict[str, Any], field_name: str) -> list[str]:
    value = frontmatter.get(field_name) or []
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{field_name} 必须是非空字符串列表")
    return list(dict.fromkeys(item.strip() for item in value))


def parse_definition(data: bytes, file_path: str, source: Source) -> Definition:
    """把单个角色文件解析为 Definition。"""

    frontmatter, body = parse_frontmatter_and_body(data)
    name = str(frontmatter.get("name", "")).strip()
    description = str(frontmatter.get("description", "")).strip()
    if not name:
        raise ValueError("frontmatter 缺少非空字段: name")
    if AGENT_NAME_REGEX.fullmatch(name) is None:
        raise ValueError(f"无效的 Agent 名称: {name}")
    if not description:
        raise ValueError("frontmatter 缺少非空字段: description")

    model = str(frontmatter.get("model") or "inherit").strip()
    if model not in VALID_MODELS:
        print(
            f'unknown model "{model}" in {file_path}; defaulting to inherit',
            file=sys.stderr,
        )
        model = "inherit"

    mode_text = str(frontmatter.get("permissionMode") or "default").strip()
    dont_ask = mode_text == "dontAsk"
    if dont_ask:
        permission_mode = Mode.DEFAULT
    else:
        permission_mode, valid_mode = parse_mode(mode_text)
        if not valid_mode:
            print(
                f'unknown permissionMode "{mode_text}" in {file_path}; defaulting to default',
                file=sys.stderr,
            )
            permission_mode = Mode.DEFAULT

    max_turns_raw = frontmatter.get("maxTurns") or 0
    if isinstance(max_turns_raw, bool):
        raise ValueError("maxTurns 必须是整数")
    try:
        max_turns = int(max_turns_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("maxTurns 必须是整数") from exc
    if max_turns < 0:
        raise ValueError("maxTurns 不能小于 0")

    isolation = str(frontmatter.get("isolation") or "").strip()
    if isolation not in VALID_ISOLATIONS:
        print(
            f'unknown isolation "{isolation}" in {file_path}; defaulting to empty',
            file=sys.stderr,
        )
        isolation = ""

    return Definition(
        name=name,
        description=description,
        tools=_string_list(frontmatter, "tools"),
        disallowed_tools=_string_list(frontmatter, "disallowedTools"),
        model=cast(Any, model),
        max_turns=max_turns,
        permission_mode=permission_mode,
        dont_ask=dont_ask,
        background=bool(frontmatter.get("background") or False),
        isolation=isolation,
        system_prompt=body,
        file_path=file_path,
        source=source,
    )


def parse_file(path: str, source: Source) -> Definition:
    """读取并解析一个角色文件。"""

    return parse_definition(Path(path).read_bytes(), str(Path(path).resolve()), source)
