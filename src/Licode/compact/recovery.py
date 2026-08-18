"""摘要之后用于恢复精确信息的三段附件。"""

from __future__ import annotations

import json

from Licode.llm import ToolDefinition

from .const import (
    ESTIMATE_CHARS_PER_TOKEN,
    RECOVERY_FILE_LIMIT,
    RECOVERY_TOKENS_PER_FILE,
)
from .state import FileReadRecord

BOUNDARY_NOTICE = (
    "需要文件原文、错误原文或用户原话时，请使用文件读取工具重新读取对应路径；"
    "不要依据摘要内容做猜测。"
)


def render_file_block(record: FileReadRecord) -> str:
    char_limit = int(RECOVERY_TOKENS_PER_FILE * ESTIMATE_CHARS_PER_TOKEN)
    content = record.content
    if len(content) > char_limit:
        content = content[:char_limit] + "\n(content truncated)"
    return f"### {record.path}\n[read at] {record.timestamp.isoformat()}\n{content}\n"


def render_tools_block(definitions: list[ToolDefinition]) -> str:
    lines: list[str] = []
    for definition in definitions:
        schema = json.dumps(
            definition.input_schema,
            separators=(",", ":"),
            ensure_ascii=False,
            sort_keys=True,
        )
        lines.append(f"- {definition.name}: {definition.description}")
        lines.append(f"  input_schema: {schema}")
    return "\n".join(lines) if lines else "(无)"


def build_recovery_attachment(
    snapshot: list[FileReadRecord],
    tool_defs: list[ToolDefinition],
) -> str:
    files = snapshot[:RECOVERY_FILE_LIMIT]
    file_text = "\n".join(render_file_block(record).rstrip() for record in files)
    if not file_text:
        file_text = "(无)"
    return "\n\n".join(
        [
            "## 最近读过的文件\n" + file_text,
            "## 当前可用工具\n" + render_tools_block(tool_defs),
            "## 边界提示\n" + BOUNDARY_NOTICE,
        ]
    )
