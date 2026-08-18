"""两层上下文管理的统一编排入口。"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from Licode.conversation import Conversation
from Licode.llm import Provider, ToolDefinition

from .const import AUTO_SAFETY_MARGIN, SUMMARY_RESERVE
from .layer1 import offload_and_snip
from .layer2 import auto_compact, force_compact
from .state import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    SessionContext,
)
from .token import estimate_tokens

logger = logging.getLogger(__name__)


class TriggerKind(Enum):
    AUTO = "auto"
    MANUAL = "manual"
    EMERGENCY = "emergency"


@dataclass
class ManageInput:
    conv: Conversation
    provider: Provider
    context_window: int
    tool_defs: list[ToolDefinition]
    replacement: ContentReplacementState
    recovery: RecoveryState
    auto_tracking: CompactCircuitBreaker
    session: SessionContext
    usage_anchor: int
    anchor_msg_len: int
    estimated_token: int
    trigger: TriggerKind


@dataclass
class ManageOutput:
    before_tokens: int
    after_tokens: int


async def manage_context(in_: ManageInput) -> ManageOutput:
    """按触发类型执行预防性落盘或全量摘要。"""

    before = in_.estimated_token
    replaced_before = in_.replacement.replacement_count()

    if in_.trigger is TriggerKind.MANUAL:
        new_messages, _, after = await force_compact(in_)
        in_.conv.replace_history(new_messages)
    else:
        current_messages = in_.conv.messages()
        layer1_out = offload_and_snip(
            current_messages,
            in_.replacement,
            in_.session,
        )
        if layer1_out != current_messages:
            in_.conv.replace_history(layer1_out)
        layer1_estimate = estimate_tokens(
            in_.usage_anchor,
            layer1_out,
            in_.anchor_msg_len,
        )

        if in_.trigger is TriggerKind.EMERGENCY:
            emergency_input = ManageInput(
                **{
                    **in_.__dict__,
                    "estimated_token": layer1_estimate,
                }
            )
            new_messages, _, after = await force_compact(emergency_input)
            in_.conv.replace_history(new_messages)
        else:
            minimum_window = SUMMARY_RESERVE + AUTO_SAFETY_MARGIN
            if in_.context_window <= minimum_window:
                logger.warning("context_window 不大于自动压缩预留，跳过自动摘要")
                after = layer1_estimate
            else:
                threshold = in_.context_window - minimum_window
                if layer1_estimate < threshold or in_.auto_tracking.tripped():
                    after = layer1_estimate
                else:
                    auto_input = ManageInput(
                        **{
                            **in_.__dict__,
                            "estimated_token": layer1_estimate,
                        }
                    )
                    new_messages, _, after = await auto_compact(auto_input)
                    in_.conv.replace_history(new_messages)

    replaced = in_.replacement.replacement_count() - replaced_before
    logger.info(
        "上下文管理完成 trigger=%s before=%s after=%s replaced=%s",
        in_.trigger.value,
        before,
        after,
        replaced,
    )
    return ManageOutput(before_tokens=before, after_tokens=after)
