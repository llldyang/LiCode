import json
import sys
from pathlib import Path

from Licode.tool import cwd_from_ctx, new_default_registry, resolve_path, with_cwd


def test_resolve_path_prefers_context_and_restores(tmp_path: Path) -> None:
    absolute = tmp_path / "absolute.txt"
    assert cwd_from_ctx() is None
    assert resolve_path(str(absolute)) == str(absolute)
    with with_cwd(str(tmp_path)):
        assert cwd_from_ctx() == str(tmp_path.resolve())
        assert resolve_path("") == str(tmp_path.resolve())
        assert resolve_path("nested/file.txt") == str((tmp_path / "nested/file.txt").resolve())
    assert cwd_from_ctx() is None
    assert resolve_path("relative.txt") == str((Path.cwd() / "relative.txt").resolve())


async def test_file_tools_use_context_cwd(tmp_path: Path) -> None:
    registry = new_default_registry()
    target = tmp_path / "sample.txt"
    target.write_text("old value\n", encoding="utf-8")
    with with_cwd(str(tmp_path)):
        read = await registry.execute("read_file", json.dumps({"path": "sample.txt"}))
        written = await registry.execute(
            "write_file", json.dumps({"path": "created.txt", "content": "created"})
        )
        edited = await registry.execute(
            "edit_file",
            json.dumps(
                {
                    "path": "sample.txt",
                    "old_string": "old value",
                    "new_string": "new value",
                }
            ),
        )
    assert "old value" in read.content
    assert not written.is_error and (tmp_path / "created.txt").read_text() == "created"
    assert not edited.is_error and target.read_text(encoding="utf-8") == "new value\n"


async def test_search_and_bash_tools_use_context_cwd(tmp_path: Path) -> None:
    registry = new_default_registry()
    (tmp_path / "only-here.txt").write_text("needle\n", encoding="utf-8")
    command = f'"{sys.executable}" -c "import os; print(os.getcwd())"'
    with with_cwd(str(tmp_path)):
        glob_result = await registry.execute("glob", json.dumps({"pattern": "*.txt"}))
        grep_result = await registry.execute("grep", json.dumps({"pattern": "needle"}))
        bash_result = await registry.execute("bash", json.dumps({"command": command}))
    assert glob_result.content == "only-here.txt"
    assert "only-here.txt:1:needle" in grep_result.content
    assert str(tmp_path.resolve()).lower() in bash_result.content.lower()


def test_tool_schemas_do_not_expose_cwd() -> None:
    registry = new_default_registry()
    for name in ("read_file", "write_file", "edit_file", "bash", "glob", "grep"):
        tool = registry.get(name)
        assert tool is not None
        assert "cwd" not in tool.parameters()["properties"]
