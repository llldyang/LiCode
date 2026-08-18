from Licode.compact.summary_prompt import (
    SUMMARY_SECTIONS,
    build_summary_prompt,
    extract_summary,
    serialize_conversation,
)
from Licode.llm import Message, ToolCall, ToolResult


def test_summary_prompt_has_two_phases_nine_sections_and_no_tools_instruction() -> None:
    prompt = build_summary_prompt([Message(role="user", content="原始请求")])
    assert len(prompt) == 1
    assert prompt[0].role == "user"
    assert "<analysis>" in prompt[0].content
    assert "<summary>" in prompt[0].content
    assert "不要调用任何工具" in prompt[0].content
    assert all(section in prompt[0].content for section in SUMMARY_SECTIONS)
    assert "原始请求" in prompt[0].content


def test_serialize_conversation_is_deterministic() -> None:
    messages = [
        Message(role="user", content="请求"),
        Message(
            role="assistant",
            content="读取",
            tool_calls=[ToolCall("id", "read_file", '{"path":"a"}')],
        ),
        Message(role="tool", tool_results=[ToolResult("id", "内容")]),
    ]
    assert serialize_conversation(messages) == serialize_conversation(messages)
    assert "[call read_file id=id" in serialize_conversation(messages)
    assert "[result id=id is_error=False] 内容" in serialize_conversation(messages)


def test_extract_summary_keeps_last_summary_and_falls_back() -> None:
    assert extract_summary("草稿<summary>正式</summary>尾巴") == "正式"
    assert extract_summary("<summary>旧</summary><summary>新</summary>") == "新"
    assert extract_summary("无标签") == "无标签"
