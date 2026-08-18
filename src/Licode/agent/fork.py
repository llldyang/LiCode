"""Fork 子 Agent 的消息克隆与嵌套检测。"""

import copy

from Licode.llm import ROLE_ASSISTANT, ROLE_TOOL, ROLE_USER, Message, ToolCall, ToolResult

FORK_BOILERPLATE_TAG = "<fork_boilerplate>"
FORK_BOILERPLATE = """<fork_boilerplate>
你是从父对话 Fork 出来的子 Agent。不能再次启动 Agent 或 Fork。
不要对话、提问或请求确认；直接使用工具，并严格限制在分配的任务范围内。
最终报告必须以 `Scope:` 开头，且不超过 500 字。
</fork_boilerplate>

任务：
"""


def build_forked_messages(parent_msgs: list[Message], task: str) -> list[Message]:
    """深拷贝父历史，补齐悬空工具调用，再追加 Fork 任务。"""

    cloned = copy.deepcopy(parent_msgs)
    consumed = {
        result.tool_call_id
        for message in cloned
        if message.role == ROLE_TOOL
        for result in message.tool_results
    }
    dangling: list[ToolCall] = []
    for message in cloned:
        if message.role != ROLE_ASSISTANT:
            continue
        dangling.extend(call for call in message.tool_calls if call.id not in consumed)
    if dangling:
        cloned.append(
            Message(
                role=ROLE_TOOL,
                tool_results=[
                    ToolResult(
                        tool_call_id=call.id,
                        content="[forked, skipped]",
                        is_error=True,
                    )
                    for call in dangling
                ],
            )
        )
    cloned.append(Message(role=ROLE_USER, content=FORK_BOILERPLATE + task))
    return cloned


def is_fork_context(messages: list[Message]) -> bool:
    """检查任意消息正文或工具结果中是否带 Fork 标记。"""

    for message in messages:
        if FORK_BOILERPLATE_TAG in message.content:
            return True
        if any(FORK_BOILERPLATE_TAG in result.content for result in message.tool_results):
            return True
    return False
