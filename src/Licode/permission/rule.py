"""权限规则解析与匹配。"""

from dataclasses import dataclass, field, replace

from . import Decision
from .matcher import Matcher, compile_matcher, match_command, match_path


@dataclass
class Rule:
    tool: str
    matcher: Matcher | None
    allow: bool
    raw: str = ""

    def render(self) -> str:
        return self.tool if self.matcher is None else f"{self.tool}({self.raw})"


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
                rule.matcher, target, is_file
            ):
                return Decision.DENY, rule
        for rule in self.allow:
            if match_pattern(rule.tool, friendly, is_file=False) and match_pattern(
                rule.matcher, target, is_file
            ):
                return Decision.ALLOW, rule
        return Decision.ALLOW, None


def parse_rule(value: str) -> tuple[Rule | None, str | None]:
    """解析 Tool 或 Tool(pattern)，并返回可观察的错误描述。"""

    text = value.strip()
    if not text:
        return None, "empty rule"
    if "(" not in text and ")" not in text:
        return Rule(text, None, False, text), None
    if "(" not in text or not text.endswith(")"):
        return None, "expected Tool(pattern)"
    tool, pattern = text.split("(", 1)
    tool = tool.strip()
    if not tool:
        return None, "empty tool name"
    raw = pattern[:-1]
    if not raw:
        return Rule(tool, None, False, raw), None
    try:
        matcher = compile_matcher(raw, is_command=(tool == "Bash"))
    except ValueError as exc:
        return None, str(exc)
    return Rule(tool, matcher, False, raw), None


def match_pattern(pattern: Matcher | str | None, target: str, is_file: bool = True) -> bool:
    """兼容旧调用点的匹配门面。"""

    if pattern is None or pattern == "":
        return True
    if isinstance(pattern, str):
        return match_path(pattern, target) if is_file else match_command(pattern, target)
    return pattern.match(target)


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
