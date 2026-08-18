import json
from pathlib import Path

import pytest

from Licode.llm import ToolCall
from Licode.permission import Category, Decision
from Licode.permission.matcher import compile_matcher
from Licode.permission.rule import Rule, RuleSet, escape_glob, match_pattern, parse_rule
from Licode.permission.settings import (
    SettingsError,
    categorize,
    extract_target,
    friendly_name,
    load_settings,
    to_rule_set,
)


def test_rule_parsing_and_command_file_globs() -> None:
    command, error = parse_rule("Bash(git *)")
    whole_tool, whole_error = parse_rule("Read")

    assert error is None and command is not None and command.tool == "Bash"
    assert command.raw == "git *" and command.matcher is not None
    assert whole_error is None and whole_tool is not None and whole_tool.matcher is None
    assert parse_rule("Bash(git *")[0] is None
    assert match_pattern("git *", "git status", is_file=False)
    assert not match_pattern("git *", "npm i", is_file=False)
    assert match_pattern("src/**", "src/a/b.py")
    assert not match_pattern("src/**", "docs/x")
    assert not match_pattern("src/*", "src/a/b.py")
    exact = escape_glob("src/a*b?[x].py")
    assert match_pattern(exact, "src/a*b?[x].py")
    assert not match_pattern(exact, "src/anything.py")


@pytest.mark.parametrize(
    ("raw", "hit", "miss"),
    [
        ("Bash(=git status)", "git status", "git status -s"),
        ("Bash(~^npm (install|test)$)", "npm install", "npm run dev"),
        ("Bash(!~^rm)", "ls -lh", "rm -rf ."),
    ],
)
def test_permission_rule_uses_compiled_matcher(raw: str, hit: str, miss: str) -> None:
    rule, error = parse_rule(raw)
    assert error is None and rule is not None and rule.matcher is not None
    assert rule.matcher.match(hit)
    assert not rule.matcher.match(miss)


def test_same_layer_deny_precedes_allow() -> None:
    rules = RuleSet(
        allow=[Rule("Bash", compile_matcher("git *", is_command=True), True, "git *")],
        deny=[Rule("Bash", compile_matcher("git push", is_command=True), False, "git push")],
    )

    assert rules.match("Bash", "git status") == (Decision.ALLOW, True)
    assert rules.match("Bash", "git push") == (Decision.DENY, True)
    assert rules.match("Bash", "npm test") == (Decision.ALLOW, False)


def test_external_tool_name_glob_matches_allow_and_deny() -> None:
    rules = RuleSet(
        allow=[Rule("mcp__demo__*", None, True)],
        deny=[Rule("mcp__demo__remove", None, False)],
    )

    assert rules.match("mcp__demo__echo", "") == (Decision.ALLOW, True)
    assert rules.match("mcp__demo__remove", "") == (Decision.DENY, True)
    assert rules.match("mcp__other__echo", "") == (Decision.ALLOW, False)


def test_settings_load_mapping_and_invalid_entries(tmp_path: Path, capsys) -> None:
    path = tmp_path / "settings.yaml"
    path.write_text(
        "default_mode: acceptEdits\n"
        "permissions:\n"
        "  allow: ['Bash(git *)', 'broken(']\n"
        "  deny: ['Read(.env)']\n",
        encoding="utf-8",
    )
    settings = load_settings(str(path))
    rules = to_rule_set(settings)

    assert settings.default_mode == "acceptEdits"
    assert len(rules.allow) == 1
    assert len(rules.deny) == 1
    assert "rule 'broken(' parse failed" in capsys.readouterr().err
    assert load_settings(str(tmp_path / "missing.yaml")).permissions.allow == []

    path.write_text("permissions: [", encoding="utf-8")
    with pytest.raises(SettingsError):
        load_settings(str(path))


def test_friendly_names_categories_and_target_extraction() -> None:
    expected = {
        "bash": "Bash",
        "read_file": "Read",
        "write_file": "Write",
        "edit_file": "Edit",
        "glob": "Glob",
        "grep": "Grep",
    }
    assert {name: friendly_name(name) for name in expected} == expected
    assert categorize("unknown", False) is Category.EXEC
    assert categorize("unknown", True) is Category.READ
    assert categorize("write_file", False) is Category.WRITE

    path_call = ToolCall("1", "write_file", json.dumps({"path": "src/a.py"}))
    glob_call = ToolCall("2", "glob", json.dumps({"pattern": "*.py"}))
    bash_call = ToolCall("3", "bash", json.dumps({"command": "git status"}))
    assert extract_target(path_call) == ("src/a.py", True, True)
    assert extract_target(glob_call) == (".", True, True)
    assert extract_target(bash_call) == ("git status", False, True)
    assert not extract_target(ToolCall("4", "read_file", "not-json"))[2]
    assert extract_target(ToolCall("5", "unknown", "{}")) == ("", False, False)
