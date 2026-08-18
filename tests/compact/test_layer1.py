from pathlib import Path

from Licode.compact import ContentReplacementState, SessionContext
from Licode.compact.layer1 import build_preview, offload_and_snip, spill_single
from Licode.llm import Message, ToolResult


def tool_message(*contents: tuple[str, str]) -> Message:
    return Message(
        role="tool",
        tool_results=[ToolResult(tool_id, content) for tool_id, content in contents],
    )


def test_spill_single_is_idempotent(tmp_path: Path) -> None:
    context = SessionContext("id", str(tmp_path))
    spill_single(context, "call", "第一次")
    path = tmp_path / "call"
    modified = path.stat().st_mtime_ns
    spill_single(context, "call", "第二次")
    assert path.read_text(encoding="utf-8") == "第一次"
    assert path.stat().st_mtime_ns == modified


def test_single_large_result_is_offloaded_with_stable_preview(tmp_path: Path) -> None:
    content = "行\n" * 30000
    state = ContentReplacementState()
    context = SessionContext("id", str(tmp_path))
    messages = [tool_message(("large", content))]

    first = offload_and_snip(messages, state, context)
    second = offload_and_snip(first, state, context)
    preview = first[0].tool_results[0].content

    assert preview == second[0].tool_results[0].content
    assert f"original size: {len(content.encode('utf-8'))} bytes" in preview
    assert "[head preview]" in preview
    assert str(tmp_path / "large") in preview
    assert "文件读取工具" in preview
    assert "不要凭头部预览猜测" in preview
    assert (tmp_path / "large").read_text(encoding="utf-8") == content
    head = preview.split("[head preview]\n", 1)[1].split("\n完整内容已保存", 1)[0]
    assert len(head.splitlines()) <= 20
    assert len(head.encode("utf-8")) <= 2048


def test_single_threshold_uses_utf8_bytes(tmp_path: Path) -> None:
    content = "中" * 17000
    output = offload_and_snip(
        [tool_message(("chinese", content))],
        ContentReplacementState(),
        SessionContext("id", str(tmp_path)),
    )
    assert "[content offloaded]" in output[0].tool_results[0].content


def test_aggregate_offloads_largest_minimum_count(tmp_path: Path) -> None:
    contents = [(f"id-{index}", chr(97 + index) * 45000) for index in range(5)]
    output = offload_and_snip(
        [tool_message(*contents)],
        ContentReplacementState(),
        SessionContext("id", str(tmp_path)),
    )
    replaced = [
        result for result in output[0].tool_results if "[content offloaded]" in result.content
    ]
    kept_bytes = sum(
        len(result.content.encode("utf-8"))
        for result in output[0].tool_results
        if "[content offloaded]" not in result.content
    )
    assert len(replaced) == 1
    assert kept_bytes <= 200000


def test_all_single_threshold_hits_are_excluded_from_aggregate(tmp_path: Path) -> None:
    contents = [(f"id-{index}", "x" * 80000) for index in range(3)]
    output = offload_and_snip(
        [tool_message(*contents)],
        ContentReplacementState(),
        SessionContext("id", str(tmp_path)),
    )
    assert all("[content offloaded]" in result.content for result in output[0].tool_results)


def test_spill_failure_keeps_result_retryable(tmp_path: Path, monkeypatch) -> None:
    attempts = 0

    def fail(*args, **kwargs) -> None:
        nonlocal attempts
        del args, kwargs
        attempts += 1
        raise OSError("磁盘不可写")

    monkeypatch.setattr("Licode.compact.layer1.spill_single", fail)
    state = ContentReplacementState()
    messages = [tool_message(("retry", "x" * 60000))]
    context = SessionContext("id", str(tmp_path))

    assert offload_and_snip(messages, state, context)[0].tool_results[0].content == "x" * 60000
    assert offload_and_snip(messages, state, context)[0].tool_results[0].content == "x" * 60000
    assert attempts == 2
    assert not state.has_decision("retry")


def test_build_preview_is_deterministic() -> None:
    first = build_preview(10, "head", "path")
    second = build_preview(10, "head", "path")
    assert first == second
