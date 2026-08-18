"""Worktree 名称校验与扁平化。"""

import re

MAX_SLUG_LENGTH = 64
SEGMENT_PATTERN = re.compile(r"^[a-zA-Z0-9._-]+$")


def validate_slug(name: str) -> None:
    """校验可由模型提供的 Worktree 名称，阻止路径遍历。"""

    if not name:
        raise ValueError("Worktree 名称不能为空")
    if len(name) > MAX_SLUG_LENGTH:
        raise ValueError("Worktree 名称不能超过 64 个字符")
    if name.startswith("/") or name.endswith("/"):
        raise ValueError("Worktree 名称不能以 / 开头或结尾")
    if "//" in name:
        raise ValueError("Worktree 名称不能包含空路径段")
    for segment in name.split("/"):
        if segment in {".", ".."}:
            raise ValueError("Worktree 名称不能包含 . 或 .. 路径段")
        if SEGMENT_PATTERN.fullmatch(segment) is None:
            raise ValueError(f"Worktree 名称含非法字符: {segment}")


def flat_slug(name: str) -> str:
    """把允许嵌套的名称转换为目录和分支可用的扁平名称。"""

    return name.replace("/", "+")
