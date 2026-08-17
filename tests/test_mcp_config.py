from pathlib import Path

from Licode.mcp.config import load_config


def set_home(monkeypatch, path: Path) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: path))


def test_missing_files_return_empty_config(tmp_path: Path, monkeypatch) -> None:
    set_home(monkeypatch, tmp_path / "home")

    assert load_config(str(tmp_path / "project")).servers == {}


def test_two_layers_merge_and_project_server_replaces_whole_user_server(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".Licode").mkdir(parents=True)
    project.mkdir()
    set_home(monkeypatch, home)
    (home / ".Licode" / "config.yaml").write_text(
        "mcp_servers:\n"
        "  shared:\n"
        "    type: stdio\n"
        "    command: user-command\n"
        "    args: [user-arg]\n"
        "  user-only:\n"
        "    type: http\n"
        "    url: https://user.example/mcp\n",
        encoding="utf-8",
    )
    (project / ".Licode.yaml").write_text(
        "mcp_servers:\n"
        "  shared:\n"
        "    type: http\n"
        "    url: https://project.example/mcp\n"
        "  project-only:\n"
        "    type: stdio\n"
        "    command: project-command\n",
        encoding="utf-8",
    )

    config = load_config(str(project))

    assert set(config.servers) == {"shared", "user-only", "project-only"}
    assert config.servers["shared"].type == "http"
    assert config.servers["shared"].url == "https://project.example/mcp"
    assert config.servers["shared"].command == ""


def test_invalid_file_is_skipped_while_other_layer_loads(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".Licode").mkdir(parents=True)
    project.mkdir()
    set_home(monkeypatch, home)
    (home / ".Licode" / "config.yaml").write_text("mcp_servers: [", encoding="utf-8")
    (project / ".Licode.yaml").write_text(
        "mcp_servers:\n  good:\n    type: stdio\n    command: python\n",
        encoding="utf-8",
    )

    config = load_config(str(project))

    assert set(config.servers) == {"good"}
    assert "[mcp] warn: load" in capsys.readouterr().err


def test_environment_expansion_is_limited_to_env_and_headers(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    project.mkdir()
    set_home(monkeypatch, home)
    monkeypatch.setenv("DEFINED", "expanded")
    monkeypatch.delenv("MISSING", raising=False)
    (project / ".Licode.yaml").write_text(
        "mcp_servers:\n"
        "  ${DEFINED}:\n"
        "    type: stdio\n"
        "    command: ${DEFINED}\n"
        "    args: ['${DEFINED}']\n"
        "    env:\n"
        "      ONE: '${DEFINED}'\n"
        "      TWO: '${MISSING}-${MISSING}'\n"
        "    headers:\n"
        "      Authorization: 'Bearer ${DEFINED}'\n",
        encoding="utf-8",
    )

    config = load_config(str(project))
    server = config.servers["${DEFINED}"]

    assert server.command == "${DEFINED}"
    assert server.args == ["${DEFINED}"]
    assert server.env == {"ONE": "expanded", "TWO": "-"}
    assert server.headers == {"Authorization": "Bearer expanded"}
    assert capsys.readouterr().err.count("undefined env var ${MISSING}") == 1


def test_invalid_servers_are_skipped_independently(tmp_path: Path, monkeypatch, capsys) -> None:
    set_home(monkeypatch, tmp_path / "home")
    project = tmp_path / "project"
    project.mkdir()
    (project / ".Licode.yaml").write_text(
        "mcp_servers:\n"
        "  missing-type: {command: python}\n"
        "  bad-type: {type: socket}\n"
        "  missing-command: {type: stdio}\n"
        "  missing-url: {type: http}\n"
        "  bad-args: {type: stdio, command: python, args: value}\n"
        "  good: {type: stdio, command: python}\n",
        encoding="utf-8",
    )

    config = load_config(str(project))
    error = capsys.readouterr().err

    assert set(config.servers) == {"good"}
    assert error.count("[mcp] warn: skip server") == 5


def test_home_resolution_failure_does_not_hide_project_config(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".Licode.yaml").write_text(
        "mcp_servers:\n  good: {type: http, url: 'https://example.test/mcp'}\n",
        encoding="utf-8",
    )

    def fail_home(cls) -> Path:
        raise OSError("home unavailable")

    monkeypatch.setattr(Path, "home", classmethod(fail_home))

    assert set(load_config(str(project)).servers) == {"good"}
    assert "load user config failed" in capsys.readouterr().err


def test_documented_example_loads_all_servers(tmp_path: Path, monkeypatch) -> None:
    set_home(monkeypatch, tmp_path / "home")
    monkeypatch.setenv("GITHUB_TOKEN", "test-github-token")
    monkeypatch.setenv("EXAMPLE_TOKEN", "test-http-token")
    project = tmp_path / "project"
    project.mkdir()
    example = Path(__file__).parents[1] / "docs" / "mcp" / "mcp-servers.example.yaml"
    (project / ".Licode.yaml").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")

    config = load_config(str(project))

    assert set(config.servers) == {"github", "local-sqlite", "example-http"}
    assert config.servers["github"].env["GITHUB_TOKEN"] == "test-github-token"
    assert config.servers["example-http"].headers["Authorization"] == ("Bearer test-http-token")
