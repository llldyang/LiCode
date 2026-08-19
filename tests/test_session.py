import json
import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from Licode.conversation import Conversation
from Licode.llm import Message, ToolCall, ToolResult
from Licode.session import Writer, clean_expired, list_sessions, load_session


def _session_dir(root: Path, session_id: str) -> Path:
    path = root / session_id
    path.mkdir(parents=True)
    return path


def test_writer_append_and_read_with_model(tmp_path: Path) -> None:
    with Writer(str(tmp_path)) as writer:
        writer.append(Message(role="user", content="你好"), "fake-model", True)
        writer.append(
            Message(
                role="assistant",
                tool_calls=[ToolCall(id="c1", name="read_file", input="{}")],
            )
        )
        writer.append(
            Message(
                role="tool",
                tool_results=[ToolResult(tool_call_id="c1", content="结果")],
            )
        )

    text = (tmp_path / "conversation.jsonl").read_text(encoding="utf-8")
    entries = [json.loads(line) for line in text.splitlines()]
    assert entries[0]["model"] == "fake-model"
    assert entries[0]["role"] == "user" and isinstance(entries[0]["ts"], int)
    assert entries[1]["tool_calls"][0]["name"] == "read_file"
    assert entries[2]["tool_results"][0]["content"] == "结果"


def test_writer_flushes_and_fsyncs_every_append(tmp_path: Path, monkeypatch) -> None:
    sync_calls: list[int] = []
    monkeypatch.setattr("Licode.session.writer.os.fsync", sync_calls.append)

    with Writer(str(tmp_path)) as writer:
        writer.append(Message(role="user", content="第一条"), "fake-model", True)
        assert "第一条" in (tmp_path / "conversation.jsonl").read_text(encoding="utf-8")
        writer.append(Message(role="assistant", content="第二条"))

    assert len(sync_calls) == 2


def test_writer_callbacks_and_compact_marker(tmp_path: Path) -> None:
    with Writer(str(tmp_path)) as writer:
        writer.set_model("model")
        writer.on_append(Message(role="user", content="旧消息"))
        writer.on_replace([Message(role="user", content="摘要")])

    text = (tmp_path / "conversation.jsonl").read_text(encoding="utf-8")
    entries = [json.loads(line) for line in text.splitlines()]
    assert entries[0]["model"] == "model"
    assert entries[1]["type"] == "compact"
    assert load_session(str(tmp_path)) == [Message(role="user", content="摘要")]


def test_writer_callback_failure_does_not_break_conversation(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    writer = Writer(str(tmp_path))
    writer.close()
    conversation = Conversation(writer.on_append, writer.on_replace)

    conversation.add_user("仍保留在内存")
    conversation.replace_messages([Message(role="user", content="摘要")])

    assert conversation.messages() == [Message(role="user", content="摘要")]
    assert "会话消息写入失败" in caplog.text
    assert "会话压缩记录写入失败" in caplog.text


def test_load_session_skips_bad_lines_and_orphaned_calls(tmp_path: Path) -> None:
    path = tmp_path / "conversation.jsonl"
    entries = [
        {"role": "user", "content": "问题", "ts": 1},
        "{bad json",
        {
            "role": "assistant",
            "tool_calls": [{"id": "c1", "name": "read_file", "input": "{}"}],
            "ts": 2,
        },
    ]
    path.write_text(
        "\n".join(item if isinstance(item, str) else json.dumps(item) for item in entries),
        encoding="utf-8",
    )

    assert load_session(str(tmp_path)) == [Message(role="user", content="问题")]


def test_load_session_ignores_incomplete_trailing_line(tmp_path: Path) -> None:
    valid = json.dumps({"role": "user", "content": "完整消息", "ts": 1})
    (tmp_path / "conversation.jsonl").write_text(
        valid + "\n" + '{"role":"assistant","content":',
        encoding="utf-8",
    )

    assert load_session(str(tmp_path)) == [Message(role="user", content="完整消息")]


def test_writer_concurrent_append_has_no_lost_or_partial_lines(tmp_path: Path) -> None:
    writer = Writer(str(tmp_path))
    barrier = threading.Barrier(21)

    def append(index: int) -> None:
        barrier.wait()
        writer.on_append(Message(role="user", content=str(index)))

    threads = [threading.Thread(target=append, args=(index,)) for index in range(20)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    writer.close()

    text = (tmp_path / "conversation.jsonl").read_text(encoding="utf-8")
    entries = [json.loads(line) for line in text.splitlines()]
    assert len(entries) == 20
    assert {entry["content"] for entry in entries} == {str(index) for index in range(20)}


def test_list_sessions_sorts_and_skips_old_format(tmp_path: Path) -> None:
    older = _session_dir(tmp_path, "20260816-120000-a1b2")
    newer = _session_dir(tmp_path, "20260817-120000-c3d4")
    old_format = _session_dir(tmp_path, "1717000000-abc12345")
    for index, directory in enumerate((older, newer, old_format)):
        (directory / "conversation.jsonl").write_text(
            json.dumps({"role": "user", "content": "x" * 60, "model": f"m{index}", "ts": 1}),
            encoding="utf-8",
        )
    old_time = datetime.now().timestamp() - 100
    os.utime(older / "conversation.jsonl", (old_time, old_time))

    sessions = list_sessions(str(tmp_path))

    assert [item.id for item in sessions] == [newer.name, older.name]
    assert len(sessions[0].title) == 50 and sessions[0].title.endswith("…")
    assert sessions[0].model == "m1"


def test_clean_expired_only_removes_new_format(tmp_path: Path) -> None:
    old_date = (datetime.now() - timedelta(days=31)).strftime("%Y%m%d-%H%M%S")
    current_date = datetime.now().strftime("%Y%m%d-%H%M%S")
    expired = _session_dir(tmp_path, f"{old_date}-dead")
    current = _session_dir(tmp_path, f"{current_date}-beef")
    old_format = _session_dir(tmp_path, "1717000000-abc12345")

    clean_expired(str(tmp_path), timedelta(days=30))

    assert not expired.exists()
    assert current.exists()
    assert old_format.exists()
