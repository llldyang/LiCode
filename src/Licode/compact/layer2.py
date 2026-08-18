"""LLM 全量摘要、恢复拼接与过长重试。"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from Licode.llm import Message, PromptTooLongError, Request

from .const import (
    ESTIMATE_CHARS_PER_TOKEN,
    MANUAL_SAFETY_MARGIN,
    PTL_DROP_PERCENTAGE,
    PTL_RETRY_LIMIT,
    RECENT_KEEP_MESSAGES,
    RECENT_KEEP_TOKENS,
    SUMMARY_RESERVE,
)
from .recovery import build_recovery_attachment
from .summary_prompt import build_summary_prompt, extract_summary
from .token import estimate_tokens, message_chars

if TYPE_CHECKING:
    from .compact import ManageInput


def pick_recent_tail(msgs: list[Message]) -> list[Message]:
    """同时满足 token 与消息数下界，并保持工具调用配对。"""

    if not msgs:
        return []
    start = len(msgs)
    total_bytes = 0
    count = 0
    for index in range(len(msgs) - 1, -1, -1):
        total_bytes += message_chars([msgs[index]])
        count += 1
        start = index
        tokens = math.ceil(total_bytes / ESTIMATE_CHARS_PER_TOKEN)
        if tokens >= RECENT_KEEP_TOKENS and count >= RECENT_KEEP_MESSAGES:
            break

    if msgs[start].role == "tool":
        result_ids = {result.tool_call_id for result in msgs[start].tool_results}
        for index in range(start - 1, -1, -1):
            calls = msgs[index].tool_calls
            if msgs[index].role == "assistant" and any(call.id in result_ids for call in calls):
                start = index
                break
    return list(msgs[start:])


def _join_after_summary(summary_and_recovery: Message, recent: list[Message]) -> list[Message]:
    recent = list(recent)
    while recent and recent[0].role == "tool":
        recent.pop(0)
    if not recent:
        return [summary_and_recovery]
    if recent[0].role == "user":
        bridge = Message(
            role="assistant",
            content="（已加载上下文摘要与恢复信息。请继续。）",
        )
        return [summary_and_recovery, bridge, *recent]
    return [summary_and_recovery, *recent]


def group_by_user_turn(msgs: list[Message]) -> list[list[Message]]:
    groups: list[list[Message]] = []
    for message in msgs:
        if message.role == "user" or not groups:
            groups.append([])
        groups[-1].append(message)
    return groups


async def summarize_once(in_: ManageInput, msgs: list[Message]) -> str:
    request = Request(messages=build_summary_prompt(msgs), tools=None)
    text_parts: list[str] = []
    async for event in in_.provider.stream(request):
        if event.err is not None:
            raise event.err
        if event.text:
            text_parts.append(event.text)
    return extract_summary("".join(text_parts))


async def ptl_retry(
    in_: ManageInput,
    msgs: list[Message],
    first_err: Exception,
) -> str:
    groups = group_by_user_turn(msgs)
    latest_error = first_err
    for _ in range(PTL_RETRY_LIMIT):
        groups = groups[1:]
        if not groups:
            raise latest_error
        try:
            return await summarize_once(in_, [item for group in groups for item in group])
        except PromptTooLongError as exc:
            latest_error = exc

    while groups:
        drop = max(1, math.ceil(len(groups) * PTL_DROP_PERCENTAGE))
        groups = groups[drop:]
        if not groups:
            break
        try:
            return await summarize_once(in_, [item for group in groups for item in group])
        except PromptTooLongError as exc:
            latest_error = exc
    raise latest_error


async def run_summary(in_: ManageInput) -> list[Message]:
    old_msgs = in_.conv.messages()
    recovery_snapshot = in_.recovery.snapshot()

    summary_input = build_summary_prompt(old_msgs)
    manual_limit = in_.context_window - SUMMARY_RESERVE - MANUAL_SAFETY_MARGIN
    prompt_tokens = estimate_tokens(0, summary_input, 0)
    if in_.trigger.value == "manual" and prompt_tokens >= manual_limit:
        summary_text = await ptl_retry(
            in_,
            old_msgs,
            PromptTooLongError("手动摘要请求预估超过上下文窗口"),
        )
    else:
        try:
            summary_text = await summarize_once(in_, old_msgs)
        except PromptTooLongError as exc:
            summary_text = await ptl_retry(in_, old_msgs, exc)

    recovery_text = build_recovery_attachment(recovery_snapshot, in_.tool_defs)
    combined = Message(
        role="user",
        content="## 历史会话摘要\n" + summary_text + "\n\n" + recovery_text,
    )
    return _join_after_summary(combined, pick_recent_tail(old_msgs))


async def auto_compact(in_: ManageInput) -> tuple[list[Message], int, int]:
    before = in_.estimated_token
    try:
        new_messages = await run_summary(in_)
    except Exception:
        in_.auto_tracking.record_failure()
        raise
    in_.auto_tracking.record_success()
    return new_messages, before, estimate_tokens(0, new_messages, 0)


async def force_compact(in_: ManageInput) -> tuple[list[Message], int, int]:
    before = in_.estimated_token
    new_messages = await run_summary(in_)
    return new_messages, before, estimate_tokens(0, new_messages, 0)
