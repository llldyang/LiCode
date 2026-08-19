"""邮箱与共享任务文件共用的跨进程锁。"""

from __future__ import annotations

import asyncio
import os
import random
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

LOCK_MAX_RETRIES = 10
LOCK_STALE_AFTER = 10.0
LOCK_BACKOFF_MIN = 0.005
LOCK_BACKOFF_MAX = 0.1


@asynccontextmanager
async def acquire(lock_path: str | Path) -> AsyncIterator[None]:
    path = Path(lock_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    acquired = False
    for _ in range(LOCK_MAX_RETRIES):
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                stale = time.time() - path.stat().st_mtime > LOCK_STALE_AFTER
            except FileNotFoundError:
                continue
            if stale:
                # 崩溃进程遗留的锁不能永久堵塞后续写入。
                with suppress(FileNotFoundError):
                    path.unlink()
                continue
            await asyncio.sleep(random.uniform(LOCK_BACKOFF_MIN, LOCK_BACKOFF_MAX))
            continue
        else:
            os.close(descriptor)
            acquired = True
            break
    if not acquired:
        raise TimeoutError(f"文件锁获取失败: {path}")
    try:
        yield
    finally:
        with suppress(FileNotFoundError):
            path.unlink()
