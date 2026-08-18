from datetime import datetime, timedelta

from Licode.compact.recovery import (
    BOUNDARY_NOTICE,
    build_recovery_attachment,
    render_file_block,
)
from Licode.compact.state import FileReadRecord
from Licode.llm import ToolDefinition


def test_render_file_block_keeps_head_and_marks_truncation() -> None:
    record = FileReadRecord("long.py", "A" * 17500 + "TAIL", datetime.now())
    rendered = render_file_block(record)
    assert "A" * 100 in rendered
    assert "TAIL" not in rendered
    assert rendered.rstrip().endswith("(content truncated)")


def test_recovery_attachment_limits_files_orders_and_matches_tools() -> None:
    now = datetime.now()
    records = [
        FileReadRecord(f"file-{index}.py", str(index), now - timedelta(seconds=index))
        for index in range(7)
    ]
    definitions = [
        ToolDefinition("read_file", "读取", {"type": "object"}),
        ToolDefinition("grep", "搜索", {"type": "object", "required": ["pattern"]}),
    ]
    rendered = build_recovery_attachment(records, definitions)

    assert "最近读过的文件" in rendered
    assert "当前可用工具" in rendered
    assert "边界提示" in rendered
    assert all(f"file-{index}.py" in rendered for index in range(5))
    assert "file-5.py" not in rendered
    assert "file-6.py" not in rendered
    assert [rendered.index(f"file-{index}.py") for index in range(5)] == sorted(
        rendered.index(f"file-{index}.py") for index in range(5)
    )
    assert "- read_file: 读取" in rendered
    assert 'input_schema: {"type":"object"}' in rendered
    assert BOUNDARY_NOTICE in rendered
    assert rendered == build_recovery_attachment(records, definitions)
