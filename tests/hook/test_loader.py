from pathlib import Path

import pytest

from Licode.hook import Event
from Licode.hook.loader import load
from Licode.hook.matcher import eval_condition, get_by_path


@pytest.mark.asyncio
async def test_load_valid_rules_and_evaluate_nested_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    (project / ".LiCode").mkdir(parents=True)
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    (project / ".LiCode" / "hooks.yaml").write_text(
        """hooks:
  - name: block-python
    event: PreToolUse
    if:
      all_of:
        - field: tool_name
          match: {type: exact, value: write_file}
        - field: tool_input.path
          match: {type: glob, value: '**/*.py'}
    action:
      type: shell
      command: exit 0
    timeout: 5s
  - name: remind
    event: SessionStart
    action:
      type: prompt
      text: use zh-CN
""",
        encoding="utf-8",
    )

    engine = load(project)

    assert [rule.name for rule in engine.rules] == ["block-python", "remind"]
    assert engine.rules[0].event is Event.PRE_TOOL_USE
    assert engine.rules[0].timeout_s == 5
    assert eval_condition(
        engine.rules[0].condition,
        {"tool_name": "write_file", "tool_input": {"path": "src/a.py"}},
    )
    assert get_by_path({"value": False}, "value") == "False"
    assert get_by_path({}, "missing.path") == ""
    await engine.close()


@pytest.mark.asyncio
async def test_loader_skips_invalid_rules_and_keeps_valid_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    (project / ".LiCode").mkdir(parents=True)
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    (project / ".LiCode" / "hooks.yaml").write_text(
        """hooks:
  - {name: unknown, event: UnknownEvent, action: {type: prompt, text: x}}
  - {name: bad-action, event: Stop, action: {type: missing}}
  - name: mixed
    event: Stop
    if: {all_of: [], any_of: []}
    action: {type: prompt, text: x}
  - name: bad-regex
    event: Stop
    if:
      all_of:
        - field: detail
          match: {type: regex, value: '['}
    action: {type: prompt, text: x}
  - name: bad-async
    event: PreToolUse
    async: true
    action: {type: shell, command: exit 0}
  - {name: good, event: Stop, action: {type: prompt, text: done}}
""",
        encoding="utf-8",
    )

    engine = load(project)

    assert [rule.name for rule in engine.rules] == ["good"]
    stderr = capsys.readouterr().err
    assert 'unknown event "UnknownEvent"' in stderr
    assert "unknown action type" in stderr
    assert "exactly one of all_of or any_of" in stderr
    assert "invalid regex" in stderr
    assert "async not allowed for blocking events" in stderr
    await engine.close()


@pytest.mark.asyncio
async def test_project_and_user_rules_merge_and_duplicate_keeps_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "project"
    home = tmp_path / "home"
    (project / ".LiCode").mkdir(parents=True)
    (home / ".LiCode").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    project_hook = project / ".LiCode" / "hooks.yaml"
    user_hook = home / ".LiCode" / "hooks.yaml"
    project_hook.write_text(
        "hooks:\n  - {name: same, event: Stop, action: {type: prompt, text: project}}\n",
        encoding="utf-8",
    )
    user_hook.write_text(
        "hooks:\n"
        "  - {name: same, event: Stop, action: {type: prompt, text: user}}\n"
        "  - {name: user-only, event: Stop, action: {type: prompt, text: user}}\n",
        encoding="utf-8",
    )

    engine = load(project)

    assert [rule.name for rule in engine.rules] == ["same", "user-only"]
    assert engine.sources == [str(project_hook), str(user_hook)]
    assert "duplicate name" in capsys.readouterr().err
    await engine.close()


def test_missing_file_is_silent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    engine = load(tmp_path)
    assert engine.rules == [] and engine.sources == []
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("content", ["hooks: [", "hooks: {}"])
def test_invalid_file_is_reported_without_raising(
    content: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    home.mkdir()
    (project / ".LiCode").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    (project / ".LiCode" / "hooks.yaml").write_text(content, encoding="utf-8")

    engine = load(project)

    assert engine.rules == []
    assert "load failed" in capsys.readouterr().err


def test_invalid_utf8_and_non_finite_timeout_are_degraded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".LiCode").mkdir(parents=True)
    (project / ".LiCode").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    (project / ".LiCode" / "hooks.yaml").write_bytes(b"\xff\xfe")
    (home / ".LiCode" / "hooks.yaml").write_text(
        "hooks:\n"
        "  - {name: bad-timeout, event: Stop, timeout: .nan, "
        "action: {type: prompt, text: x}}\n",
        encoding="utf-8",
    )

    engine = load(project)

    assert engine.rules == []
    stderr = capsys.readouterr().err
    assert "load failed" in stderr
    assert "timeout must be greater than zero" in stderr
