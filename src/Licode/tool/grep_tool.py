"""正则搜索文件内容工具。"""

import asyncio
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from . import Result
from .ctx import resolve_path

MAX_LINE_LENGTH = 1024 * 1024


class GrepTool:
    read_only = True
    is_system = False

    def name(self) -> str:
        return "grep"

    def description(self) -> str:
        return "使用 Python 正则搜索文件内容，返回文件、行号和命中内容。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Python 正则表达式"},
                "path": {"type": "string", "description": "搜索路径，默认当前目录"},
                "glob": {"type": "string", "description": "可选的文件名 glob 过滤"},
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
        for key in ("path", "glob"):
            if key in data and not isinstance(data[key], str):
                return Result(content=f"参数 {key} 必须是字符串", is_error=True)
        try:
            pattern = re.compile(data["pattern"])
        except re.error as exc:
            return Result(content=f"正则非法: {exc}", is_error=True)

        root = Path(resolve_path(data.get("path") or "."))
        if not root.exists():
            return Result(content=f"搜索路径不存在: {root}", is_error=True)
        files: Iterable[Path]
        if root.is_file():
            files = [root]
        else:
            files = root.rglob(data.get("glob") or "*")

        matches: list[str] = []
        for path in files:
            if not path.is_file():
                continue
            try:
                with path.open(encoding="utf-8", errors="replace") as handle:
                    for line_number, line in enumerate(handle, 1):
                        searched = line[:MAX_LINE_LENGTH]
                        if pattern.search(searched):
                            rendered = searched.rstrip()
                            if len(line) > MAX_LINE_LENGTH:
                                rendered += " [该行过长，未完整搜索]"
                            matches.append(f"{path}:{line_number}:{rendered}")
                            if len(matches) > 100:
                                return Result(content="\n".join(matches[:100]) + "\n[truncated]")
            except (OSError, UnicodeDecodeError):
                continue
            await asyncio.sleep(0)

        if not matches:
            return Result(content="无命中")
        return Result(content="\n".join(matches))
