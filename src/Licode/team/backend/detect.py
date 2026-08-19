"""按固定优先级检测 Team 执行后端。"""

import os
import shutil

from Licode.team.types import BackendType


def detect() -> BackendType:
    if os.environ.get("TMUX"):
        return BackendType.TMUX
    if os.environ.get("TERM_PROGRAM") == "iTerm.app" and shutil.which("it2"):
        return BackendType.ITERM2
    if shutil.which("tmux"):
        return BackendType.TMUX
    return BackendType.IN_PROCESS


__all__ = ["detect"]
