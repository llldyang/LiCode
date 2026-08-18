"""无需精确 tokenizer 的上下文 token 估算。"""

from __future__ import annotations

import json
import math
from typing import Any

from Licode.llm import Message, Usage

from .const import ESTIMATE_CHARS_PER_TOKEN


def _encoded_size(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return len(text.encode("utf-8"))


def message_chars(msgs: list[Message]) -> int:
    """计算消息及其工具数据的 UTF-8 字节总量。"""

    total = 0
    for message in msgs:
        total += _encoded_size(message.content)
        total += sum(_encoded_size(call.input) for call in message.tool_calls)
        total += sum(_encoded_size(result.content) for result in message.tool_results)
    return total


def estimate_tokens(anchor: int, all_msgs: list[Message], anchor_msg_len: int) -> int:
    """以最近真实 usage 为锚点，只估算其后新增消息。"""

    start = min(max(anchor_msg_len, 0), len(all_msgs))
    return anchor + math.ceil(message_chars(all_msgs[start:]) / ESTIMATE_CHARS_PER_TOKEN)


def usage_anchor(usage: Usage) -> int:
    """把 provider usage 合并为下一轮估算锚点。"""

    return usage.input_tokens + usage.output_tokens + usage.cache_read + usage.cache_write
