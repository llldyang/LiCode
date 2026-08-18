"""权限规则与 Hook 条件共用的匹配器。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol


class Matcher(Protocol):
    """匹配器统一接口。"""

    def match(self, value: str) -> bool: ...

    def __str__(self) -> str: ...


def _glob_regex(pattern: str, is_file: bool) -> str:
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern):
            parts.append(re.escape(pattern[index + 1]))
            index += 2
            continue
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                parts.append(".*")
                index += 2
            else:
                parts.append("[^/]*" if is_file else ".*")
                index += 1
            continue
        parts.append(re.escape(char))
        index += 1
    return "".join(parts)


def match_command(pattern: str, value: str) -> bool:
    """按整条命令执行 glob 匹配。"""

    return re.fullmatch(_glob_regex(pattern, False), value) is not None


def match_path(pattern: str, value: str) -> bool:
    """按规范化路径执行 glob 匹配，单星号不跨目录。"""

    normalized = value.replace("\\", "/")
    return re.fullmatch(_glob_regex(pattern, True), normalized) is not None


@dataclass(frozen=True)
class ExactMatcher:
    """整串精确匹配。"""

    value: str

    def match(self, value: str) -> bool:
        return value == self.value

    def __str__(self) -> str:
        return f"={self.value}"


@dataclass(frozen=True)
class GlobMatcher:
    """兼容既有权限规则的 glob 匹配。"""

    pattern: str
    is_command: bool

    def match(self, value: str) -> bool:
        if self.is_command:
            return match_command(self.pattern, value)
        return match_path(self.pattern, value)

    def __str__(self) -> str:
        return self.pattern


@dataclass(frozen=True)
class RegexMatcher:
    """使用预编译正则搜索目标字符串。"""

    src: str
    compiled: re.Pattern[str]

    def match(self, value: str) -> bool:
        return self.compiled.search(value) is not None

    def __str__(self) -> str:
        return f"~{self.src}"


@dataclass(frozen=True)
class NotMatcher:
    """对任意内层匹配器结果取反。"""

    inner: Matcher

    def match(self, value: str) -> bool:
        return not self.inner.match(value)

    def __str__(self) -> str:
        return f"!{self.inner}"


def compile_matcher(pattern: str, *, is_command: bool) -> Matcher:
    """把单字符前缀语法编译为可复用匹配器。"""

    if not pattern:
        raise ValueError("empty matcher pattern")
    head, rest = pattern[0], pattern[1:]
    if head == "=":
        return ExactMatcher(rest)
    if head == "~":
        try:
            return RegexMatcher(rest, re.compile(rest))
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
    if head == "!":
        return NotMatcher(compile_matcher(rest, is_command=is_command))
    return GlobMatcher(pattern, is_command)


__all__ = [
    "ExactMatcher",
    "GlobMatcher",
    "Matcher",
    "NotMatcher",
    "RegexMatcher",
    "compile_matcher",
    "match_command",
    "match_path",
]
