from Licode.conversation import Conversation
from Licode.llm import Message, ToolCall, ToolResult


def test_messages_keep_order_and_roles() -> None:
    conversation = Conversation()
    conversation.add_user("第一轮")
    conversation.add_assistant("回答")
    conversation.add_user("第二轮")

    messages = conversation.messages()

    assert [(message.role, message.content) for message in messages] == [
        ("user", "第一轮"),
        ("assistant", "回答"),
        ("user", "第二轮"),
    ]


def test_messages_returns_copy() -> None:
    conversation = Conversation()
    conversation.add_user("不会被外部列表修改")

    messages = conversation.messages()
    messages.clear()

    assert len(conversation.messages()) == 1


def test_tool_calls_and_results_keep_protocol_neutral_history() -> None:
    conversation = Conversation()
    call = ToolCall(id="call-1", name="read_file", input='{"path":"README.md"}')
    result = ToolResult(tool_call_id="call-1", content="文件内容")

    conversation.add_user("读取文件")
    conversation.add_assistant_with_tool_calls("我来读取。", [call])
    conversation.add_tool_results([result])
    conversation.add_assistant("读取完成。")

    messages = conversation.messages()
    assert [message.role for message in messages] == ["user", "assistant", "tool", "assistant"]
    assert messages[1].tool_calls == [call]
    assert messages[2].tool_results == [result]


def test_last_role_tracks_history_tail() -> None:
    conversation = Conversation()
    assert conversation.last_role() == ""

    conversation.add_user("用户")
    assert conversation.last_role() == "user"
    conversation.add_tool_results([ToolResult(tool_call_id="call-1", content="结果")])
    assert conversation.last_role() == "tool"
    conversation.add_assistant("助手")
    assert conversation.last_role() == "assistant"


def test_replace_history_deep_copies_and_accepts_empty() -> None:
    conversation = Conversation()
    source = [Message(role="user", content="原文")]
    conversation.replace_history(source)
    source[0].content = "外部修改"
    source.clear()
    assert conversation.messages()[0].content == "原文"
    assert conversation.length() == 1

    conversation.replace_history(None)
    assert conversation.messages() == []
    conversation.replace_history([])
    assert conversation.length() == 0
