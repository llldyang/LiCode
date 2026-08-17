"""权限规则解析与精确/glob 匹配。"""

import re
from dataclasses import dataclass, field, replace

from . import Decision


@dataclass
class Rule:
    tool: str
    pattern: str
    allow: bool

    def render(self) -> str:
        return self.tool if not self.pattern else f"{self.tool}({self.pattern})"


@dataclass
class RuleSet:
    allow: list[Rule] = field(default_factory=list)
    deny: list[Rule] = field(default_factory=list)

    def match(self, friendly: str, target: str) -> tuple[Decision, bool]:
        decision, rule = self.match_rule(friendly, target)
        return decision, rule is not None

    def match_rule(self, friendly: str, target: str) -> tuple[Decision, Rule | None]:
        is_file = friendly != "Bash"
        for rule in self.deny:
            if match_pattern(rule.tool, friendly, is_file=False) and match_pattern(
                rule.pattern, target, is_file
            ):
                return Decision.DENY, rule
        for rule in self.allow:
            if match_pattern(rule.tool, friendly, is_file=False) and match_pattern(
                rule.pattern, target, is_file
            ):
                return Decision.ALLOW, rule
        return Decision.ALLOW, None


def parse_rule(value: str) -> tuple[Rule, bool]:
    """解析 Tool 或 Tool(pattern) 形式的规则。"""

    text = value.strip()
    if not text:
        return Rule("", "", False), False
    if "(" not in text and ")" not in text:
        return Rule(text, "", False), True
    if "(" not in text or not text.endswith(")"):
        return Rule("", "", False), False
    tool, pattern = text.split("(", 1)
    tool = tool.strip()
    if not tool:
        return Rule("", "", False), False
    return Rule(tool, pattern[:-1], False), True


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


def match_pattern(pattern: str, target: str, is_file: bool = True) -> bool:
    if not pattern:
        return True
    normalized_target = target.replace("\\", "/") if is_file else target
    return re.fullmatch(_glob_regex(pattern, is_file), normalized_target) is not None


def with_allow(rule: Rule, allow: bool) -> Rule:
    return replace(rule, allow=allow)


def escape_glob(value: str) -> str:
    """转义精确规则中的 glob 元字符。"""

    escaped: list[str] = []
    for char in value:
        if char in {"\\", "*", "?", "[", "]"}:
            escaped.append("\\")
        escaped.append(char)
    return "".join(escaped)
