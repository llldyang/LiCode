"""唯一匹配编辑文件工具。"""

import json
from pathlib import Path
from typing import Any

from . import Result


class EditFileTool:
    def name(self) -> str:
        return "edit_file"

    def description(self) -> str:
        return "用 new_string 替换文件中唯一匹配的 old_string。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要修改的文件路径"},
                "old_string": {
                    "type": "string",
                    "description": "必须在文件中唯一匹配的原文",
                },
                "new_string": {"type": "string", "description": "替换后的新文本"},
            },
            "required": ["path", "old_string", "new_string"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            return Result(content=f"参数 JSON 非法: {exc}", is_error=True)
        if not isinstance(data, dict):
            return Result(content="工具参数必须是 JSON 对象", is_error=True)
        for key in ("path", "old_string", "new_string"):
            if not isinstance(data.get(key), str):
                return Result(content=f"缺少字符串参数: {key}", is_error=True)

        path = Path(data["path"])
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return Result(content=f"读取文件失败: {path}: {exc}", is_error=True)

        old_string = data["old_string"]
        count = content.count(old_string)
        if count == 0:
            return Result(content="未找到匹配的内容", is_error=True)
        if count > 1:
            return Result(
                content=f"匹配到 {count} 处，old_string 不唯一，请提供更长上下文使其唯一",
                is_error=True,
            )
        try:
            path.write_text(content.replace(old_string, data["new_string"], 1), encoding="utf-8")
        except OSError as exc:
            return Result(content=f"写入文件失败: {path}: {exc}", is_error=True)
        return Result(content=f"已更新 {path}")
