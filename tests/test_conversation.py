from Licode.conversation import Conversation


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
