"""项目根路径沙箱与符号链接安全解析。"""

import os
from pathlib import Path
from typing import Protocol


class Rooted(Protocol):
    root: str


def resolve_root(root: str) -> str:
    """把项目根解析为真实存在的绝对路径。"""

    return str(Path(root).expanduser().resolve(strict=True))


def eval_symlinks_or_ancestor(abs_path: str) -> str:
    """解析目标符号链接；目标不存在时从最近的已存在祖先恢复。"""

    target = Path(abs_path)
    missing: list[str] = []
    ancestor = target
    while not ancestor.exists():
        if ancestor.parent == ancestor:
            raise FileNotFoundError(abs_path)
        missing.append(ancestor.name)
        ancestor = ancestor.parent
    resolved = ancestor.resolve(strict=True)
    for part in reversed(missing):
        resolved /= part
    return str(resolved)


def resolved_target(root: str, path: str) -> str:
    target = Path(path).expanduser() if path else Path(root)
    if not target.is_absolute():
        target = Path(root) / target
    return eval_symlinks_or_ancestor(str(target))


def sandbox_ok(engine: Rooted, path: str) -> bool:
    """判断解析后的路径是否位于项目根或系统临时目录内。"""

    try:
        resolved = resolved_target(engine.root, path)
        root = os.path.normcase(os.path.normpath(engine.root))
        target = os.path.normcase(os.path.normpath(resolved))
        return target == root or target.startswith(root + os.sep) or is_system_temp_path(path)
    except (OSError, ValueError):
        return False


def project_relative(root: str, path: str) -> str:
    """将已通过沙箱的目标转换为 slash 风格项目相对路径。"""

    resolved = Path(resolved_target(root, path))
    relative = resolved.relative_to(Path(root))
    return relative.as_posix() or "."


def is_system_temp_path(path: str) -> bool:
    """仅开放文档指定的 /tmp 与 /private/tmp，仍按真实路径阻断软链逃逸。"""

    try:
        target = os.path.normcase(os.path.normpath(eval_symlinks_or_ancestor(path)))
        roots = {
            os.path.normcase(os.path.normpath(eval_symlinks_or_ancestor(candidate)))
            for candidate in ("/tmp", "/private/tmp")
        }
    except (OSError, ValueError):
        return False
    return any(target == root or target.startswith(root + os.sep) for root in roots)
