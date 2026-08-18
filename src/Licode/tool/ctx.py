"""工具调用的显式工作目录上下文。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_ctx_cwd: ContextVar[str | None] = ContextVar("cwd", default=None)


@contextmanager
def with_cwd(directory: str) -> Iterator[None]:
    """在当前异步上下文中设置工具工作目录。"""

    if not directory:
        yield
        return
    token = _ctx_cwd.set(str(Path(directory).resolve()))
    try:
        yield
    finally:
        _ctx_cwd.reset(token)


def cwd_from_ctx() -> str | None:
    return _ctx_cwd.get()


def resolve_path(path: str) -> str:
    """以显式 cwd 优先解析路径，并返回绝对路径。"""

    base = Path(_ctx_cwd.get() or Path.cwd())
    if not path:
        return str(base.resolve())
    candidate = Path(path)
    if candidate.is_absolute():
        return str(candidate)
    return str((base / candidate).resolve())
