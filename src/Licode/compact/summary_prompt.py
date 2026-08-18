"""结构化会话摘要的固定提示与解析。"""

from __future__ import annotations

import json
import logging
import re

from Licode.llm import Message

logger = logging.getLogger(__name__)

SUMMARY_SECTIONS = (
    "## 1 主要请求和意图",
    "## 2 关键技术概念",
    "## 3 文件和代码段",
    "## 4 错误和修复",
    "## 5 问题解决过程",
    "## 6 所有用户消息原文",
    "## 7 待办任务",
    "## 8 当前工作（最详细）",
    "## 9 可能的下一步",
)

SUMMARY_INSTRUCTION = """你正在总结一个编程 Agent 的会话。请分两个阶段输出。

第一阶段在 <analysis>...</analysis> 中写分析草稿。分析草稿只帮助你整理信息，
不会被保留。

第二阶段在 <summary>...</summary> 中写正式摘要，并严格使用下面九个小节：
## 1 主要请求和意图
## 2 关键技术概念
## 3 文件和代码段
## 4 错误和修复
## 5 问题解决过程
## 6 所有用户消息原文
按时间顺序逐条保留所有用户消息原文。
## 7 待办任务
## 8 当前工作（最详细）
## 9 可能的下一步

不要调用任何工具，输出纯文本。不要省略正在进行的工作、文件路径、错误原文和待办事项。"""


def serialize_conversation(msgs: list[Message]) -> str:
    """把协议无关的消息历史序列化为稳定可读文本。"""

    lines: list[str] = []
    for message in msgs:
        if message.content:
            lines.append(f"{message.role}: {message.content}")
        elif not message.tool_calls and not message.tool_results:
            lines.append(f"{message.role}:")
        for call in message.tool_calls:
            lines.append(
                f"[call {call.name} id={call.id} args={json.dumps(call.input, ensure_ascii=False)}]"
            )
        for result in message.tool_results:
            lines.append(
                f"[result id={result.tool_call_id} is_error={result.is_error}] {result.content}"
            )
    return "\n".join(lines)


def build_summary_prompt(msgs: list[Message]) -> list[Message]:
    content = SUMMARY_INSTRUCTION + "\n\n[conversation]\n" + serialize_conversation(msgs)
    return [Message(role="user", content=content)]


def extract_summary(raw: str) -> str:
    matches = re.findall(r"<summary>(.*?)</summary>", raw, re.DOTALL)
    if matches:
        return matches[-1].strip()
    logger.warning("summary tags not found")
    return raw
