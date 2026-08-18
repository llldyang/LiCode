"""按新格式会话 ID 清理过期目录。"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from Licode.compact import parse_session_time

logger = logging.getLogger(__name__)


def clean_expired(sessions_dir: str, max_age: timedelta) -> None:
    root = Path(sessions_dir)
    if not root.is_dir():
        return
    now = datetime.now()
    try:
        directories = list(root.iterdir())
    except OSError as exc:
        logger.warning("扫描会话目录失败 %s: %s", root, exc)
        return
    for directory in directories:
        if not directory.is_dir():
            continue
        try:
            created = parse_session_time(directory.name)
        except ValueError:
            continue
        if now - created <= max_age:
            continue
        try:
            shutil.rmtree(directory)
        except OSError as exc:
            logger.warning("清理过期会话失败 %s: %s", directory, exc)
