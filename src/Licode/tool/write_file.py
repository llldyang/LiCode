"""写入文件工具。"""

import json
from pathlib import Path
from typing import Any

from . import Result


class WriteFileTool:
    read_only = False

    def name(self) -> str:
        return "write_file"

    def description(self) -> str:
        return "创建或覆盖文本文件，并自动创建父目录。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要写入的文件路径"},
                "content": {"type": "string", "description": "要写入的完整内容"},
            },
            "required": ["path", "content"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            return Result(content=f"参数 JSON 非法: {exc}", is_error=True)
        if not isinstance(data, dict) or not isinstance(data.get("path"), str):
            return Result(content="缺少字符串参数: path", is_error=True)
        if not isinstance(data.get("content"), str):
            return Result(content="缺少字符串参数: content", is_error=True)

        path = Path(data["path"])
        content = data["content"]
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            return Result(content=f"写入文件失败: {path}: {exc}", is_error=True)
        return Result(content=f"已写入 {path}（{len(content.encode())} 字节）")
