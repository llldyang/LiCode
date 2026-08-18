import json
import sys
from pathlib import Path

import pytest

from Licode.tool import Registry, new_default_registry


def test_registry_exports_six_definitions_in_order() -> None:
    registry = new_default_registry()

    assert [definition.name for definition in registry.definitions()] == [
        "read_file",
        "write_file",
        "edit_file",
        "bash",
        "glob",
        "grep",
    ]
    assert registry.get("read_file") is not None
    assert registry.get("missing") is None
    assert registry.count() == 6
    assert [definition.name for definition in registry.read_only_definitions()] == [
        "read_file",
        "glob",
        "grep",
    ]
    assert registry.is_read_only("read_file")
    assert not registry.is_read_only("write_file")
    assert not registry.is_read_only("missing")


@pytest.mark.asyncio
async def test_registry_reports_unknown_tool() -> None:
    result = await Registry().execute("missing", "{}")

    assert result.is_error
    assert "未知工具" in result.content


@pytest.mark.asyncio
async def test_read_file_handles_file_missing_and_directory(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("第一行\n第二行", encoding="utf-8")
    tool = new_default_registry().get("read_file")
    assert tool is not None

    result = await tool.execute(json.dumps({"path": str(target)}))
    missing = await tool.execute(json.dumps({"path": str(tmp_path / "missing.txt")}))
    directory = await tool.execute(json.dumps({"path": str(tmp_path)}))

    assert "     1\t第一行" in result.content
    assert "     2\t第二行" in result.content
    assert missing.is_error
    assert directory.is_error


@pytest.mark.asyncio
async def test_write_file_creates_parent_and_overwrites(tmp_path: Path) -> None:
    target = tmp_path / "a" / "b" / "sample.txt"
    tool = new_default_registry().get("write_file")
    assert tool is not None

    first = await tool.execute(json.dumps({"path": str(target), "content": "旧内容"}))
    second = await tool.execute(json.dumps({"path": str(target), "content": "新内容"}))

    assert not first.is_error
    assert not second.is_error
    assert target.read_text(encoding="utf-8") == "新内容"


@pytest.mark.asyncio
async def test_edit_file_requires_unique_match(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    tool = new_default_registry().get("edit_file")
    assert tool is not None

    target.write_text("唯一内容", encoding="utf-8")
    success = await tool.execute(
        json.dumps({"path": str(target), "old_string": "唯一", "new_string": "替换"})
    )
    assert target.read_text(encoding="utf-8") == "替换内容"
    missing = await tool.execute(
        json.dumps({"path": str(target), "old_string": "不存在", "new_string": "替换"})
    )
    target.write_text("重复 重复", encoding="utf-8")
    multiple = await tool.execute(
        json.dumps({"path": str(target), "old_string": "重复", "new_string": "替换"})
    )

    assert not success.is_error
    assert missing.is_error and "未找到" in missing.content
    assert multiple.is_error and "2 处" in multiple.content
    assert missing.content != multiple.content


@pytest.mark.asyncio
async def test_bash_returns_output_exit_code_and_timeout() -> None:
    registry = new_default_registry()

    success = await registry.execute("bash", json.dumps({"command": "echo hi"}))
    failure = await registry.execute(
        "bash", json.dumps({"command": f'"{sys.executable}" -c "raise SystemExit(7)"'})
    )
    timeout = await registry.execute(
        "bash",
        json.dumps({"command": f'"{sys.executable}" -c "import time; time.sleep(5)"'}),
        timeout=0.05,
    )

    assert not success.is_error
    assert "hi" in success.content
    assert "exit_code: 0" in success.content
    assert not failure.is_error
    assert "exit_code: 7" in failure.content
    assert timeout.is_error
    assert "超时" in timeout.content


@pytest.mark.asyncio
async def test_glob_and_grep_find_expected_content(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pkg"
    source.mkdir(parents=True)
    (source / "one.py").write_text("needle = 1\n", encoding="utf-8")
    (source / "two.txt").write_text("needle = 2\n", encoding="utf-8")
    registry = new_default_registry()

    glob_result = await registry.execute(
        "glob", json.dumps({"path": str(tmp_path), "pattern": "**/*.py"})
    )
    grep_result = await registry.execute(
        "grep",
        json.dumps({"path": str(tmp_path), "glob": "*.py", "pattern": "needle"}),
    )

    assert "one.py" in glob_result.content
    assert "one.py:1:needle = 1" in grep_result.content


@pytest.mark.asyncio
async def test_large_tool_results_are_truncated(tmp_path: Path) -> None:
    target = tmp_path / "large.txt"
    target.write_text("\n".join(f"line {index}" for index in range(2100)), encoding="utf-8")
    registry = new_default_registry()

    read_result = await registry.execute("read_file", json.dumps({"path": str(target)}))
    bash_result = await registry.execute(
        "bash",
        json.dumps({"command": f'"{sys.executable}" -c "print(\'x\'*31000)"'}),
    )
    grep_result = await registry.execute(
        "grep", json.dumps({"path": str(target), "pattern": "line"})
    )

    assert read_result.content.endswith("[truncated]")
    assert bash_result.content.endswith("[truncated]")
    assert grep_result.content.endswith("[truncated]")
