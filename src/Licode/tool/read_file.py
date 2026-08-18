"""读取文件工具。"""

import json
from pathlib import Path
from typing import Any

from . import Result, _truncate


class ReadFileTool:
    read_only = True
    is_system = False

    def name(self) -> str:
        return "read_file"

    def description(self) -> str:
        return "读取文本文件并返回带行号的内容。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "要读取的文件路径"}},
            "required": ["path"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            return Result(content=f"参数 JSON 非法: {exc}", is_error=True)
        if not isinstance(data, dict) or not isinstance(data.get("path"), str):
            return Result(content="缺少字符串参数: path", is_error=True)

        path = Path(data["path"])
        if not path.exists():
            return Result(content=f"文件不存在: {path}", is_error=True)
        if path.is_dir():
            return Result(content=f"路径是目录，无法读取: {path}", is_error=True)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return Result(content=f"读取文件失败: {path}: {exc}", is_error=True)

        numbered = "\n".join(
            f"{number:6d}\t{line}" for number, line in enumerate(text.splitlines(), 1)
        )
        return Result(content=_truncate(numbered, max_lines=2000, max_chars=256 * 1024))
