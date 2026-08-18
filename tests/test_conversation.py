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


def test_append_and_replace_callbacks_receive_copies() -> None:
    appended: list[Message] = []
    replaced: list[list[Message]] = []
    conversation = Conversation(appended.append, replaced.append)

    conversation.add_user("用户")
    conversation.add_assistant("助手")
    conversation.add_assistant_with_tool_calls(
        "调用",
        [ToolCall(id="call-1", name="read_file", input="{}")],
    )
    conversation.add_tool_results([ToolResult(tool_call_id="call-1", content="结果")])
    conversation.replace_messages([Message(role="user", content="摘要")])

    assert [message.role for message in appended] == ["user", "assistant", "assistant", "tool"]
    assert replaced == [[Message(role="user", content="摘要")]]
    appended[0].content = "外部修改"
    replaced[0][0].content = "外部修改"
    assert conversation.messages() == [Message(role="user", content="摘要")]


def test_from_messages_copies_history_without_firing_callbacks() -> None:
    appended: list[Message] = []
    source = [Message(role="user", content="已有消息")]
    conversation = Conversation.from_messages(source, appended.append)

    source[0].content = "外部修改"
    assert conversation.messages()[0].content == "已有消息"
    assert appended == []
