import json
from pathlib import Path

from Licode.llm import ToolCall
from Licode.permission import Decision, Mode, new_engine


def test_permanent_allow_is_exact_idempotent_and_reloads(tmp_path: Path, monkeypatch) -> None:
    user_home = tmp_path / "home"
    user_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: user_home))
    root = tmp_path / "project"
    root.mkdir()
    engine, _ = new_engine(str(root))
    call = ToolCall(
        "write",
        "write_file",
        json.dumps({"path": str(root / "src" / "file.py"), "content": "x"}),
    )

    engine.persist_local_allow(call)
    engine.persist_local_allow(call)

    content = Path(engine.local_path).read_text(encoding="utf-8")
    assert content.count("Write(src/file.py)") == 1
    reloaded, err = new_engine(str(root))
    assert err is None
    assert reloaded.check(Mode.DEFAULT, call, False) == (Decision.ALLOW, "")


def test_permanent_allow_supports_targetless_external_tool(tmp_path: Path, monkeypatch) -> None:
    user_home = tmp_path / "home"
    user_home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: user_home))
    root = tmp_path / "project"
    root.mkdir()
    engine, _ = new_engine(str(root))
    call = ToolCall("mcp", "mcp__demo__echo", json.dumps({"text": "hello"}))

    engine.persist_local_allow(call)

    content = Path(engine.local_path).read_text(encoding="utf-8")
    assert "- mcp__demo__echo\n" in content
    reloaded, err = new_engine(str(root))
    assert err is None
    assert reloaded.check(Mode.DEFAULT, call, False) == (Decision.ALLOW, "")
