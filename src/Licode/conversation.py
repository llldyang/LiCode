"""进程内的单会话多轮历史。"""

import copy
import threading
from collections.abc import Callable

from Licode.llm import ROLE_ASSISTANT, ROLE_TOOL, ROLE_USER, Message, ToolCall, ToolResult


class Conversation:
    def __init__(
        self,
        on_append: Callable[[Message], None] | None = None,
        on_replace: Callable[[list[Message]], None] | None = None,
    ) -> None:
        self._messages: list[Message] = []
        self._lock = threading.RLock()
        self._on_append = on_append
        self._on_replace = on_replace

    @classmethod
    def from_messages(
        cls,
        messages: list[Message],
        on_append: Callable[[Message], None] | None = None,
        on_replace: Callable[[list[Message]], None] | None = None,
    ) -> "Conversation":
        """从已有消息的深拷贝创建会话。"""

        conversation = cls(on_append=on_append, on_replace=on_replace)
        conversation._messages = copy.deepcopy(list(messages))
        return conversation

    def _append(self, message: Message) -> None:
        with self._lock:
            self._messages.append(message)
        if self._on_append is not None:
            self._on_append(copy.deepcopy(message))

    def add_user(self, text: str) -> None:
        self._append(Message(role=ROLE_USER, content=text))

    def add_assistant(self, text: str) -> None:
        self._append(Message(role=ROLE_ASSISTANT, content=text))

    def add_assistant_with_tool_calls(self, text: str, calls: list[ToolCall]) -> None:
        """追加 assistant 工具调用回合。"""

        self._append(Message(role=ROLE_ASSISTANT, content=text, tool_calls=list(calls)))

    def add_tool_results(self, results: list[ToolResult]) -> None:
        """追加工具执行结果回合。"""

        self._append(Message(role=ROLE_TOOL, tool_results=list(results)))

    def messages(self) -> list[Message]:
        with self._lock:
            return copy.deepcopy(self._messages)

    def replace_history(self, messages: list[Message] | None) -> None:
        """用深拷贝后的新消息序列整体替换历史。"""

        self.replace_messages(messages or [])

    def replace_messages(self, messages: list[Message]) -> None:
        """整体替换历史并通知持久化回调。"""

        with self._lock:
            self._messages = copy.deepcopy(list(messages))
            snapshot = copy.deepcopy(self._messages)
        if self._on_replace is not None:
            self._on_replace(snapshot)

    def length(self) -> int:
        with self._lock:
            return len(self._messages)

    def last_role(self) -> str:
        """返回最后一条消息角色，空历史返回空字符串。"""

        with self._lock:
            return self._messages[-1].role if self._messages else ""
