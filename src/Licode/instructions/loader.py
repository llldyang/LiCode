"""三层 LiCode.md 加载与 @include 展开。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

INCLUDE_RE = re.compile(r"^@include\s+(.+)$")


@dataclass
class Loader:
    project_root: str
    user_home: str | None = None
    max_depth: int = 5

    def __post_init__(self) -> None:
        if self.user_home is None:
            self.user_home = os.path.expanduser("~")

    def load(self) -> str:
        """按项目根、项目配置、用户配置的顺序加载指令。"""

        project_root = Path(self.project_root).resolve()
        user_config = Path(self.user_home or os.path.expanduser("~")).resolve() / ".Licode"
        candidates = (
            (project_root / "LiCode.md", project_root),
            (project_root / ".Licode" / "LiCode.md", project_root),
            (user_config / "LiCode.md", user_config),
        )
        contents: list[str] = []
        for path, boundary in candidates:
            content = self._load_file(str(path), str(boundary), 1, set())
            if content:
                contents.append(content)
        return "\n\n".join(contents)

    def _load_file(
        self,
        path: str,
        boundary: str,
        depth: int,
        visited: set[str],
    ) -> str:
        """加载单个文件，并递归展开独占一行的 include。"""

        real_path = os.path.realpath(path)
        real_boundary = os.path.realpath(boundary)
        display_path = path
        if depth > self.max_depth:
            return f"<!-- @include 超过最大嵌套深度，已跳过: {display_path} -->"
        if real_path in visited:
            return f"<!-- @include 检测到环路，已跳过: {display_path} -->"
        try:
            if os.path.commonpath((real_path, real_boundary)) != real_boundary:
                return f"<!-- @include 路径超出允许范围，已跳过: {display_path} -->"
        except ValueError:
            return f"<!-- @include 路径超出允许范围，已跳过: {display_path} -->"

        try:
            data = Path(real_path).read_bytes()
        except OSError:
            return ""
        if b"\x00" in data[:512]:
            return f"<!-- @include 二进制文件不可读，已跳过: {display_path} -->"

        try:
            text = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            return ""

        visited.add(real_path)
        try:
            output: list[str] = []
            for line in text.splitlines(keepends=True):
                stripped = line.rstrip("\r\n")
                match = INCLUDE_RE.fullmatch(stripped)
                if match is None:
                    output.append(line)
                    continue
                include_path = os.path.join(os.path.dirname(real_path), match.group(1))
                expanded = self._load_file(
                    include_path,
                    real_boundary,
                    depth + 1,
                    visited,
                )
                output.append(expanded)
                if line.endswith(("\n", "\r")) and expanded and not expanded.endswith("\n"):
                    output.append("\n")
            return "".join(output).rstrip("\r\n")
        finally:
            visited.remove(real_path)
