import json
from pathlib import Path

import pytest

from Licode.llm import ToolCall
from Licode.permission import Category, Decision
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
    command, ok = parse_rule("Bash(git *)")
    whole_tool, whole_ok = parse_rule("Read")

    assert ok and command.tool == "Bash" and command.pattern == "git *"
    assert whole_ok and whole_tool.pattern == ""
    assert not parse_rule("Bash(git *")[1]
    assert match_pattern("git *", "git status", is_file=False)
    assert not match_pattern("git *", "npm i", is_file=False)
    assert match_pattern("src/**", "src/a/b.py")
    assert not match_pattern("src/**", "docs/x")
    assert not match_pattern("src/*", "src/a/b.py")
    exact = escape_glob("src/a*b?[x].py")
    assert match_pattern(exact, "src/a*b?[x].py")
    assert not match_pattern(exact, "src/anything.py")


def test_same_layer_deny_precedes_allow() -> None:
    rules = RuleSet(
        allow=[Rule("Bash", "git *", True)],
        deny=[Rule("Bash", "git push", False)],
    )

    assert rules.match("Bash", "git status") == (Decision.ALLOW, True)
    assert rules.match("Bash", "git push") == (Decision.DENY, True)
    assert rules.match("Bash", "npm test") == (Decision.ALLOW, False)


def test_settings_load_mapping_and_invalid_entries(tmp_path: Path) -> None:
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
