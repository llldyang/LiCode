import json
from pathlib import Path

from Licode.llm import ToolCall
from Licode.permission import Category, Decision, Mode, mode_fallback, new_engine, parse_mode
from Licode.permission.matcher import compile_matcher
from Licode.permission.rule import Rule, RuleSet


def call(name: str, **args: str) -> ToolCall:
    return ToolCall("call", name, json.dumps(args))


def rule(tool: str, pattern: str, allow: bool) -> Rule:
    matcher = compile_matcher(pattern, is_command=(tool == "Bash")) if pattern else None
    return Rule(tool, matcher, allow, pattern)


def test_mode_names_parser_and_fallback_matrix() -> None:
    assert [str(mode) for mode in Mode] == [
        "default",
        "acceptEdits",
        "plan",
        "bypassPermissions",
    ]
    assert parse_mode("AcCePtEdItS") == (Mode.ACCEPT_EDITS, True)
    assert parse_mode("x") == (Mode.DEFAULT, False)
    expected = {
        Mode.DEFAULT: (Decision.ALLOW, Decision.ASK, Decision.ASK),
        Mode.ACCEPT_EDITS: (Decision.ALLOW, Decision.ALLOW, Decision.ASK),
        Mode.PLAN: (Decision.ALLOW, Decision.ASK, Decision.ASK),
        Mode.BYPASS: (Decision.ALLOW, Decision.ALLOW, Decision.ALLOW),
    }
    for mode, decisions in expected.items():
        assert tuple(mode_fallback(mode, category) for category in Category) == decisions


def test_blacklist_and_sandbox_precede_bypass_and_rules(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    engine, err = new_engine(str(root))
    assert err is None
    engine.local.allow.append(rule("Bash", "rm -rf /", True))
    engine.local.allow.append(rule("Read", "*", True))

    danger = engine.check(Mode.BYPASS, call("bash", command="rm -rf /"), False)
    outside = engine.check(Mode.BYPASS, call("read_file", path=str(tmp_path / "outside.txt")), True)
    inside = engine.check(Mode.DEFAULT, call("read_file", path="inside.txt"), True)
    non_command = engine.check(Mode.BYPASS, call("write_file", path="rm -rf safe.txt"), False)
    bash_with_path = engine.check(Mode.DEFAULT, call("bash", command="cat ../outside.txt"), False)

    assert danger[0] is Decision.DENY and "黑名单" in danger[1]
    assert outside[0] is Decision.DENY and "项目目录之外" in outside[1]
    assert inside == (Decision.ALLOW, "")
    assert non_command == (Decision.ALLOW, "")
    assert bash_with_path[0] is Decision.ASK


def test_rule_priority_exact_glob_and_mode_short_circuit(tmp_path: Path) -> None:
    engine, _ = new_engine(str(tmp_path))
    engine.user = RuleSet(allow=[rule("Bash", "git *", True)])
    engine.project = RuleSet(allow=[rule("Bash", "git push", True)])
    engine.local = RuleSet(deny=[rule("Bash", "git push", False)])

    assert engine.check(Mode.DEFAULT, call("bash", command="git status"), False) == (
        Decision.ALLOW,
        "",
    )
    denied = engine.check(Mode.BYPASS, call("bash", command="git push"), False)
    assert denied[0] is Decision.DENY and "Bash(git push)" in denied[1]
    assert engine.check(Mode.DEFAULT, call("bash", command="npm test"), False)[0] is Decision.ASK

    engine.local = RuleSet(allow=[rule("Write", "src/**", True)])
    assert (
        engine.check(Mode.DEFAULT, call("write_file", path="src/a/b.py"), False)[0]
        is Decision.ALLOW
    )
    assert engine.check(Mode.DEFAULT, call("write_file", path="docs/x"), False)[0] is Decision.ASK

    engine.local = RuleSet(allow=[rule("Bash", "git push", True)])
    engine.project = RuleSet(deny=[rule("Bash", "git push", False)])
    engine.user = RuleSet(deny=[rule("Bash", "git push", False)])
    assert engine.check(Mode.DEFAULT, call("bash", command="git push"), False)[0] is Decision.ALLOW

    engine.local = RuleSet()
    engine.project = RuleSet(allow=[rule("Bash", "git push", True)])
    assert engine.check(Mode.DEFAULT, call("bash", command="git push"), False)[0] is Decision.ALLOW

    engine.project = RuleSet()
    assert engine.check(Mode.BYPASS, call("bash", command="git push"), False)[0] is Decision.DENY


def test_friendly_rules_route_to_all_six_builtin_tools(tmp_path: Path) -> None:
    engine, _ = new_engine(str(tmp_path))
    engine.local = RuleSet(
        deny=[
            rule("Bash", "git status", False),
            rule("Read", "read.txt", False),
            rule("Write", "write.txt", False),
            rule("Edit", "edit.txt", False),
            rule("Glob", ".", False),
            rule("Grep", ".", False),
        ]
    )
    samples = [
        (call("bash", command="git status"), False),
        (call("read_file", path="read.txt"), True),
        (call("write_file", path="write.txt"), False),
        (call("edit_file", path="edit.txt"), False),
        (call("glob", path=".", pattern="*.py"), True),
        (call("grep", path=".", pattern="text"), True),
    ]

    for tool_call, read_only in samples:
        decision, reason = engine.check(Mode.BYPASS, tool_call, read_only)
        assert decision is Decision.DENY
        assert "匹配 deny 规则" in reason


def test_safe_defaults_for_malformed_and_unknown_calls(tmp_path: Path) -> None:
    engine, _ = new_engine(str(tmp_path))

    malformed_file = engine.check(Mode.BYPASS, ToolCall("1", "write_file", "not-json"), False)
    malformed_bash = engine.check(Mode.DEFAULT, ToolCall("2", "bash", "not-json"), False)
    unknown = engine.check(Mode.DEFAULT, ToolCall("3", "unknown", "{}"), False)

    assert malformed_file[0] is Decision.DENY
    assert malformed_bash[0] is Decision.ASK
    assert unknown[0] is Decision.ASK


def test_three_layer_loading_default_mode_and_invalid_config_degrade(
    tmp_path: Path, monkeypatch
) -> None:
    root = tmp_path / "project"
    user_home = tmp_path / "home"
    (root / ".Licode").mkdir(parents=True)
    (user_home / ".Licode").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: user_home))
    (user_home / ".Licode" / "settings.yaml").write_text(
        "default_mode: acceptEdits\npermissions:\n  deny: ['Bash(git push)']\n",
        encoding="utf-8",
    )
    (root / ".Licode" / "settings.yaml").write_text(
        "default_mode: plan\npermissions:\n  allow: ['Bash(git push)']\n",
        encoding="utf-8",
    )
    (root / ".Licode" / "settings.local.yaml").write_text(
        "default_mode: bypassPermissions\npermissions:\n  deny: ['Bash(git push)']\n",
        encoding="utf-8",
    )

    engine, err = new_engine(str(root))
    assert err is None
    assert engine.start_mode() is Mode.BYPASS
    assert engine.check(Mode.BYPASS, call("bash", command="git push"), False)[0] is Decision.DENY

    (root / ".Licode" / "settings.local.yaml").write_text("permissions: [", encoding="utf-8")
    degraded, err = new_engine(str(root))
    assert err is None
    assert degraded.start_mode() is Mode.PLAN
    assert (
        degraded.check(Mode.DEFAULT, call("bash", command="git push"), False)[0] is Decision.ALLOW
    )

    (root / ".Licode" / "settings.local.yaml").unlink()
    (root / ".Licode" / "settings.yaml").unlink()
    user_only, err = new_engine(str(root))
    assert err is None
    assert user_only.start_mode() is Mode.ACCEPT_EDITS
    assert user_only.check(Mode.BYPASS, call("bash", command="git push"), False)[0] is Decision.DENY

    (user_home / ".Licode" / "settings.yaml").unlink()
    empty, err = new_engine(str(root))
    assert err is None
    assert empty.start_mode() is Mode.DEFAULT


def test_unresolvable_root_still_returns_safe_engine(tmp_path: Path) -> None:
    engine, err = new_engine(str(tmp_path / "missing"))

    assert err is not None
    assert engine.start_mode() is Mode.DEFAULT
    assert engine.check(Mode.DEFAULT, call("bash", command="git status"), False)[0] is Decision.ASK
