"""解析带 YAML frontmatter 的 Skill 文件。"""

import re
from pathlib import Path
from typing import Any, cast

import yaml

from .types import ForkContext, Skill, SkillMeta, SkillMode, SkillSource

_VALID_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
_VALID_MODES = {"inline", "fork"}
_VALID_CONTEXTS = {"none", "recent", "full"}


class SkillParseError(ValueError):
    """单个 Skill 文件不满足格式约束。"""


def parse_frontmatter(raw: str) -> tuple[dict[str, Any], str]:
    """拆分并解析 ``---`` 包围的 YAML frontmatter。"""

    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillParseError("缺少开头 frontmatter 分隔符 ---")
    try:
        closing = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise SkillParseError("frontmatter 未闭合") from exc

    frontmatter_text = "\n".join(lines[1:closing])
    try:
        loaded = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as exc:
        raise SkillParseError(f"frontmatter YAML 无效: {exc}") from exc
    if not isinstance(loaded, dict):
        raise SkillParseError("frontmatter 必须是 YAML 映射")
    body = "\n".join(lines[closing + 1 :]).strip()
    return cast(dict[str, Any], loaded), body


def _required_text(meta: dict[str, Any], name: str) -> str:
    value = meta.get(name)
    if not isinstance(value, str) or not value.strip():
        raise SkillParseError(f"frontmatter 缺少非空字段: {name}")
    return value.strip()


def _validate_meta(meta: dict[str, Any]) -> SkillMeta:
    name = _required_text(meta, "name")
    description = _required_text(meta, "description")
    if _VALID_NAME.fullmatch(name) is None:
        raise SkillParseError(f"无效的 skill 名称: {name}")

    allowed_raw = meta.get("allowed_tools", meta.get("allowed-tools", []))
    if allowed_raw is None:
        allowed_raw = []
    if not isinstance(allowed_raw, list) or any(
        not isinstance(item, str) or not item.strip() for item in allowed_raw
    ):
        raise SkillParseError("allowed_tools 必须是非空字符串列表")
    allowed_tools = list(dict.fromkeys(item.strip() for item in allowed_raw))

    mode_raw = meta.get("mode", "inline") or "inline"
    if not isinstance(mode_raw, str) or mode_raw not in _VALID_MODES:
        raise SkillParseError("mode 必须是 inline 或 fork")

    context_raw = meta.get("fork_context", meta.get("context", "none")) or "none"
    if not isinstance(context_raw, str) or context_raw not in _VALID_CONTEXTS:
        raise SkillParseError("context 必须是 none、recent 或 full")

    model_raw = meta.get("model")
    if model_raw is not None and (not isinstance(model_raw, str) or not model_raw.strip()):
        raise SkillParseError("model 必须是非空字符串")

    return SkillMeta(
        name=name,
        description=description,
        allowed_tools=allowed_tools,
        mode=cast(SkillMode, mode_raw),
        fork_context=cast(ForkContext, context_raw),
        model=model_raw.strip() if isinstance(model_raw, str) else None,
    )


def parse_skill_file(
    path: Path,
    source: SkillSource,
    *,
    is_directory: bool | None = None,
) -> Skill:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SkillParseError(f"Skill 文件不存在: {path}") from exc
    except (OSError, UnicodeError) as exc:
        raise SkillParseError(f"无法读取 Skill 文件 {path}: {exc}") from exc

    meta_raw, body = parse_frontmatter(raw)
    meta = _validate_meta(meta_raw)
    directory_layout = path.name == "SKILL.md" if is_directory is None else is_directory
    return Skill(
        meta=meta,
        prompt_body=body,
        source_dir=path.parent.resolve(),
        source_path=path.resolve(),
        source=source,
        is_directory=directory_layout,
    )


def parse_skill_dir(dir_path: Path, source: SkillSource) -> Skill:
    return parse_skill_file(dir_path / "SKILL.md", source, is_directory=True)


def substitute_arguments(prompt_body: str, args: str) -> str:
    return prompt_body.replace("$ARGUMENTS", args)


__all__ = [
    "SkillParseError",
    "parse_frontmatter",
    "parse_skill_dir",
    "parse_skill_file",
    "substitute_arguments",
]
