"""按 Glob 模式查找文件工具。"""

import asyncio
import json
from pathlib import Path
from typing import Any

from . import Result


class GlobTool:
    read_only = True

    def name(self) -> str:
        return "glob"

    def description(self) -> str:
        return "按 glob 模式递归查找文件，最多返回 100 个结果。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "如 **/*.py 的 glob 模式"},
                "path": {"type": "string", "description": "搜索根目录，默认当前目录"},
            },
            "required": ["pattern"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            return Result(content=f"参数 JSON 非法: {exc}", is_error=True)
        if not isinstance(data, dict) or not isinstance(data.get("pattern"), str):
            return Result(content="缺少字符串参数: pattern", is_error=True)
        if "path" in data and not isinstance(data["path"], str):
            return Result(content="参数 path 必须是字符串", is_error=True)

        root = Path(data.get("path") or ".")
        if not root.is_dir():
            return Result(content=f"搜索目录不存在: {root}", is_error=True)
        matches: list[str] = []
        try:
            for index, path in enumerate(root.glob(data["pattern"]), 1):
                if path.is_file():
                    matches.append(str(path.relative_to(root)))
                if index % 100 == 0:
                    await asyncio.sleep(0)
        except (OSError, ValueError) as exc:
            return Result(content=f"glob 搜索失败: {exc}", is_error=True)

        if not matches:
            return Result(content="无匹配")
        matches.sort()
        if len(matches) > 100:
            return Result(content="\n".join(matches[:100]) + "\n[truncated]")
        return Result(content="\n".join(matches))
