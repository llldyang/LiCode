"""动态运行环境采集与渲染。"""

import datetime
import os
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class Environment:
    """供模型感知、但不进入稳定缓存块的环境信息。"""

    working_dir: str
    platform: str
    date: str
    git_status: str
    version: str
    model: str

    def render(self) -> str:
        """按固定顺序渲染非空环境字段。"""

        fields = [
            ("Working directory", self.working_dir),
            ("Platform", self.platform),
            ("Date", self.date),
            ("Git status", self.git_status),
            ("LiCode version", self.version),
            ("Model", self.model),
        ]
        lines = ["Environment information (dynamic, uncached):"]
        lines.extend(f"{key}: {value}" for key, value in fields if value)
        return "\n".join(lines)


def _git_status() -> str:
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    changes = [line for line in completed.stdout.splitlines() if line]
    if not changes:
        return "clean"
    return f"{len(changes)} changed file(s)"


def gather_environment(version: str, model: str) -> Environment:
    """快速采集环境；任一可选项失败时降级为空值。"""

    try:
        working_dir = os.getcwd()
    except OSError:
        working_dir = ""
    try:
        today = datetime.date.today().isoformat()
    except (OSError, ValueError):
        today = ""
    return Environment(
        working_dir=working_dir,
        platform=sys.platform,
        date=today,
        git_status=_git_status(),
        version=version,
        model=model,
    )
