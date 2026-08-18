"""由 Agent 调用的远程 Skill 安装工具。"""

import inspect
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from Licode.skills import Catalog
from Licode.skills.install import SkillInstallError, install_from_url

from . import Result

InstalledCallback = Callable[[], Awaitable[None] | None]


class InstallSkillTool:
    read_only = False
    is_system = False
    is_system_tool = False

    def __init__(self, catalog: Catalog, work_dir: Path) -> None:
        self._catalog = catalog
        self._work_dir = work_dir
        self._on_installed: InstalledCallback | None = None

    def set_on_installed(self, callback: InstalledCallback) -> None:
        self._on_installed = callback

    def name(self) -> str:
        return "InstallSkill"

    def description(self) -> str:
        return "从 skills.sh 或 GitHub URL 安装 Skill 到用户目录。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Skill 的远程 URL"}},
            "required": ["url"],
        }

    async def execute(self, args: str) -> Result:
        try:
            data = json.loads(args or "{}")
        except (json.JSONDecodeError, TypeError) as exc:
            return Result(f"参数 JSON 非法: {exc}", is_error=True)
        url = data.get("url") if isinstance(data, dict) else None
        if not isinstance(url, str) or not url.strip():
            return Result("缺少字符串参数: url", is_error=True)
        try:
            name = await install_from_url(url.strip(), self._catalog, self._work_dir)
            if self._on_installed is not None:
                outcome = self._on_installed()
                if inspect.isawaitable(outcome):
                    await outcome
        except (SkillInstallError, OSError) as exc:
            return Result(f"Skill 安装失败: {exc}", is_error=True)
        return Result(f"Skill {name} installed and reloaded.")


InstallSkill = InstallSkillTool
