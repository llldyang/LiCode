from pathlib import Path

import pytest

from Licode.permission import Mode
from Licode.subagent import Source, parse_definition, parse_file


def definition_bytes(extra: str = "", body: str = "正文") -> bytes:
    return (f"---\nname: Tester\ndescription: 测试角色\n{extra}---\n\n{body}").encode()


def test_definition_fields() -> None:
    definition = parse_definition(
        definition_bytes(
            "tools: [read_file]\ndisallowedTools: [bash]\nmodel: sonnet\n"
            "maxTurns: 7\npermissionMode: dontAsk\nbackground: true\nisolation: worktree\n"
        ),
        "test.md",
        Source.PROJECT,
    )
    assert definition.name == "Tester"
    assert definition.description == "测试角色"
    assert definition.tools == ["read_file"]
    assert definition.disallowed_tools == ["bash"]
    assert definition.model == "sonnet"
    assert definition.max_turns == 7
    assert definition.permission_mode is Mode.DEFAULT
    assert definition.dont_ask
    assert definition.background
    assert definition.isolation == "worktree"
    assert definition.system_prompt == "正文"
    assert definition.file_path == "test.md"
    assert definition.source is Source.PROJECT


@pytest.mark.parametrize(
    "raw",
    [
        b"---\ndescription: x\n---\nbody",
        b"---\nname: x\n---\nbody",
        b"---\nname: x\ndescription: y\n",
    ],
)
def test_invalid_required_frontmatter(raw: bytes) -> None:
    with pytest.raises(ValueError):
        parse_definition(raw, "bad.md", Source.USER)


@pytest.mark.parametrize(
    "extra",
    [
        "maxTurns: 1.5\n",
        "maxTurns: '7'\n",
        "background: 'yes'\n",
    ],
)
def test_invalid_field_types_are_rejected(extra: str) -> None:
    with pytest.raises(ValueError):
        parse_definition(definition_bytes(extra), "bad.md", Source.USER)


def test_description_must_be_a_string() -> None:
    raw = b"---\nname: Tester\ndescription: 123\n---\nbody"
    with pytest.raises(ValueError):
        parse_definition(raw, "bad.md", Source.USER)


def test_invalid_fields_fallback(capsys: pytest.CaptureFixture[str]) -> None:
    definition = parse_definition(
        definition_bytes("model: gpt-4\npermissionMode: strange\nisolation: container\n"),
        "bad.md",
        Source.USER,
    )
    assert definition.model == "inherit"
    assert definition.permission_mode is Mode.DEFAULT
    assert definition.isolation == ""
    captured = capsys.readouterr().err
    assert 'unknown model "gpt-4"' in captured
    assert 'unknown permissionMode "strange"' in captured
    assert 'unknown isolation "container"' in captured


def test_isolation_defaults_to_empty() -> None:
    definition = parse_definition(definition_bytes(), "test.md", Source.USER)
    assert definition.isolation == ""


def test_plan_mode_required_is_parsed() -> None:
    definition = parse_definition(
        definition_bytes("planModeRequired: true\n"), "planner.md", Source.USER
    )
    assert definition.plan_mode_required is True


@pytest.mark.parametrize("value", ["false", "[]", "{}", "1"])
def test_non_string_isolation_warns_and_falls_back(
    value: str, capsys: pytest.CaptureFixture[str]
) -> None:
    definition = parse_definition(definition_bytes(f"isolation: {value}\n"), "bad.md", Source.USER)
    assert definition.isolation == ""
    assert "unknown isolation" in capsys.readouterr().err


def test_parse_file_and_bom(tmp_path: Path) -> None:
    path = tmp_path / "agent.md"
    path.write_bytes(b"\xef\xbb\xbf" + definition_bytes(body="完整正文\n第二行"))
    assert parse_file(str(path), Source.USER).system_prompt == "完整正文\n第二行"
