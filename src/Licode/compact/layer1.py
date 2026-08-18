"""工具结果的预防性落盘与稳定预览替换。"""

from __future__ import annotations

import copy
import logging
from pathlib import Path

from Licode.llm import Message

from .const import (
    MESSAGE_AGGREGATE_LIMIT,
    PREVIEW_HEAD_BYTES,
    PREVIEW_HEAD_LINES,
    SINGLE_RESULT_LIMIT,
)
from .state import ContentReplacementState, SessionContext

logger = logging.getLogger(__name__)


def spill_single(session: SessionContext, tool_use_id: str, content: str) -> None:
    """幂等地把完整工具结果写入会话目录。"""

    path = Path(session.spill_dir) / tool_use_id
    if path.exists():
        return
    path.write_bytes(content.encode("utf-8"))


def _head_preview(content: str) -> str:
    head = "".join(content.splitlines(keepends=True)[:PREVIEW_HEAD_LINES])
    encoded = head.encode("utf-8")[:PREVIEW_HEAD_BYTES]
    return encoded.decode("utf-8", errors="ignore")


def build_preview(original_bytes: int, head: str, spill_path: str) -> str:
    """构造可稳定复用的工具结果预览体。"""

    return "\n".join(
        [
            f"[content offloaded] original size: {original_bytes} bytes",
            f"[saved to] {spill_path}",
            "[head preview]",
            head,
            "完整内容已保存到上述路径，如需查看请用文件读取工具读取该路径，不要凭头部预览猜测全文",
        ]
    )


def offload_and_snip(
    msgs: list[Message],
    state: ContentReplacementState,
    session: SessionContext,
) -> list[Message]:
    """对每条工具消息执行单条阈值和聚合阈值决策。"""

    out = copy.deepcopy(msgs)
    for message in out:
        if message.role != "tool":
            continue

        candidates: list[tuple[int, int, str, str]] = []
        remaining_bytes = 0
        for index, result in enumerate(message.tool_results):
            result_id = result.tool_call_id
            content = result.content
            size = len(content.encode("utf-8"))
            if state.has_decision(result_id):
                stored_replacement = state.replacement_for(result_id)
                resolved = state.decide_once(
                    result_id,
                    content,
                    lambda: ("kept", ""),
                )
                result.content = resolved
                if stored_replacement is None:
                    remaining_bytes += size
                continue
            candidates.append((size, index, result_id, content))
            remaining_bytes += size

        candidates.sort(key=lambda item: item[0], reverse=True)
        replace_ids: set[str] = set()
        for size, _, result_id, _ in candidates:
            if size > SINGLE_RESULT_LIMIT:
                replace_ids.add(result_id)
                remaining_bytes -= size
        for size, _, result_id, _ in candidates:
            if remaining_bytes <= MESSAGE_AGGREGATE_LIMIT:
                break
            if result_id in replace_ids:
                continue
            replace_ids.add(result_id)
            remaining_bytes -= size

        for size, index, result_id, content in candidates:
            if result_id not in replace_ids:
                message.tool_results[index].content = state.decide_once(
                    result_id,
                    content,
                    lambda: ("kept", ""),
                )
                continue

            spill_path = str(Path(session.spill_dir) / result_id)

            def decide(
                *,
                result_id: str = result_id,
                content: str = content,
                size: int = size,
                spill_path: str = spill_path,
            ) -> tuple[str, str]:
                try:
                    spill_single(session, result_id, content)
                    preview = build_preview(size, _head_preview(content), spill_path)
                except (OSError, ValueError) as exc:
                    logger.warning("工具结果落盘失败，保留原文 %s: %s", result_id, exc)
                    return "skip", ""
                return "replaced", preview

            message.tool_results[index].content = state.decide_once(
                result_id,
                content,
                decide,
            )
    return out
