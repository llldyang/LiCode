from pathlib import Path

from Licode.subagent import Source, builtin_definitions, load_catalog


def write_agent(path: Path, description: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: Explore\ndescription: {description}\n---\n\n{description}",
        encoding="utf-8",
    )


def test_builtin() -> None:
    definitions = builtin_definitions()
    assert [item.name for item in definitions] == ["Explore", "Plan", "general-purpose"]
    assert all(item.source is Source.BUILTIN for item in definitions)


def test_project_overrides_builtin(tmp_path: Path) -> None:
    write_agent(tmp_path / ".Licode" / "agents" / "explore.md", "项目定义")
    catalog = load_catalog(str(tmp_path))
    resolved = catalog.resolve("Explore")
    assert resolved is not None
    assert resolved.source is Source.PROJECT
    assert resolved.description == "项目定义"


def test_fork_definition() -> None:
    definition = load_catalog(".").fork_definition()
    assert definition.is_fork()
    assert definition.max_turns == 25


def test_invalid_project_definition_is_skipped(tmp_path: Path, capsys) -> None:
    path = tmp_path / ".Licode" / "agents" / "bad.md"
    path.parent.mkdir(parents=True)
    path.write_text("bad", encoding="utf-8")
    catalog = load_catalog(str(tmp_path))
    assert catalog.resolve("bad") is None
    assert "跳过 Agent 定义" in capsys.readouterr().err
