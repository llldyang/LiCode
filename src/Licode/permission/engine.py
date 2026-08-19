"""权限引擎与黑名单到模式兜底的前四层流水线。"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from Licode.llm import ToolCall

from . import Category, Decision, Mode, parse_mode
from .blacklist import hits_blacklist, patterns
from .rule import RuleSet
from .sandbox import is_system_temp_path, project_relative, resolve_root, sandbox_ok
from .settings import (
    Settings,
    categorize,
    extract_target,
    friendly_name,
    load_settings,
    to_rule_set,
)


@dataclass
class Engine:
    root: str
    blacklist: tuple[re.Pattern[str], ...] = field(default_factory=patterns)
    user: RuleSet = field(default_factory=RuleSet)
    project: RuleSet = field(default_factory=RuleSet)
    local: RuleSet = field(default_factory=RuleSet)
    local_path: str = ""
    _start_mode: Mode = Mode.DEFAULT

    def check(self, mode: Mode, call: ToolCall, read_only: bool) -> tuple[Decision, str]:
        """按黑名单、沙箱、三级规则、模式兜底依次短路判定。"""

        category = categorize(call.name, read_only)
        friendly = friendly_name(call.name)
        target, is_file, ok = extract_target(call)

        if category is Category.EXEC and target and hits_blacklist(target, self.blacklist):
            return Decision.DENY, f"命中危险命令黑名单：{target}"

        rule_target = target
        if is_file:
            if not ok:
                return Decision.DENY, "无法解析文件路径参数，安全拒绝"
            if not sandbox_ok(self, target):
                return Decision.DENY, f"路径在项目目录之外：{target}"
            if is_system_temp_path(target):
                rule_target = target
            else:
                try:
                    rule_target = project_relative(self.root, target)
                except (OSError, ValueError):
                    return Decision.DENY, f"路径在项目目录之外：{target}"

        for rules in (self.local, self.project, self.user):
            decision, matched = rules.match_rule(friendly, rule_target)
            if matched is None:
                continue
            if decision is Decision.DENY:
                return decision, f"匹配 deny 规则：{matched.render()}"
            return Decision.ALLOW, ""

        fallback = mode_fallback(mode, category)
        if fallback is Decision.ALLOW:
            return fallback, ""
        category_name = {
            Category.READ: "只读",
            Category.WRITE: "文件写",
            Category.EXEC: "命令执行",
        }[category]
        return fallback, f"{mode} 模式下 {category_name} 类操作需确认"

    def start_mode(self) -> Mode:
        return self._start_mode

    def persist_local_allow(self, call: ToolCall) -> None:
        from .persist import persist_local_allow

        persist_local_allow(self, call)


def _load_or_empty(path: str) -> Settings:
    try:
        return load_settings(path)
    except Exception:
        return Settings()


def new_engine(root: str) -> tuple[Engine, Exception | None]:
    """构造权限引擎；配置错误降级，项目根错误返回安全空引擎。"""

    try:
        resolved_root = resolve_root(root)
    except Exception as exc:
        fallback = str(Path(root).expanduser())
        return (
            Engine(
                root=fallback,
                local_path=str(Path(fallback) / ".Licode" / "settings.local.yaml"),
            ),
            exc,
        )

    user_path = str(Path.home() / ".Licode" / "settings.yaml")
    project_path = str(Path(resolved_root) / ".Licode" / "settings.yaml")
    local_path = str(Path(resolved_root) / ".Licode" / "settings.local.yaml")
    user_settings = _load_or_empty(user_path)
    project_settings = _load_or_empty(project_path)
    local_settings = _load_or_empty(local_path)

    initial_mode = Mode.DEFAULT
    for settings in (local_settings, project_settings, user_settings):
        parsed, ok = parse_mode(settings.default_mode)
        if ok:
            initial_mode = parsed
            break

    return (
        Engine(
            root=resolved_root,
            user=to_rule_set(user_settings),
            project=to_rule_set(project_settings),
            local=to_rule_set(local_settings),
            local_path=local_path,
            _start_mode=initial_mode,
        ),
        None,
    )


def mode_fallback(mode: Mode, category: Category) -> Decision:
    """规则未命中时按模式和类别返回 Allow 或 Ask。"""

    if category is Category.READ or mode is Mode.BYPASS:
        return Decision.ALLOW
    if mode is Mode.ACCEPT_EDITS and category is Category.WRITE:
        return Decision.ALLOW
    return Decision.ASK


def start_mode(engine: Engine) -> Mode:
    return engine.start_mode()
