"""Worktree 创建、快速恢复与环境初始化。"""

from __future__ import annotations

import fnmatch
import os
import shutil
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .git import _resolve_head_sha_from_fs, _resolve_initial_head_sha_from_fs, _run_git
from .manager import Worktree
from .slug import flat_slug, validate_slug

if TYPE_CHECKING:
    from .manager import Manager


def _warn(step: str, exc: BaseException) -> None:
    print(f"worktree: setup {step}: {exc}", file=sys.stderr)


def copy_local_configs(repo_root: Path, wt_path: Path) -> None:
    for relative in (Path(".Licode/config.yaml"), Path(".Licode/settings.local.yaml")):
        source = repo_root / relative
        target = wt_path / relative
        if not source.is_file() or target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


async def setup_git_hooks(repo_root: Path, wt_path: Path) -> None:
    husky = repo_root / ".husky"
    hooks_path = ""
    if husky.is_dir():
        hooks_path = str(husky.resolve())
    else:
        try:
            configured = await _run_git(repo_root, "config", "--get", "core.hooksPath")
        except RuntimeError:
            configured = ""
        if configured:
            candidate = Path(configured)
            resolved = candidate.resolve() if candidate.is_absolute() else repo_root / candidate
            hooks_path = str(resolved.resolve())
    if hooks_path:
        # 普通 git config 会修改共享配置；启用 worktreeConfig 后只写当前副本。
        await _run_git(repo_root, "config", "extensions.worktreeConfig", "true")
        await _run_git(wt_path, "config", "--worktree", "core.hooksPath", hooks_path)


def symlink_large_dirs(repo_root: Path, wt_path: Path, directories: list[str]) -> None:
    for name in directories:
        source = repo_root / name
        target = wt_path / name
        if not source.exists() or target.exists():
            continue
        os.symlink(source.resolve(), target, target_is_directory=source.is_dir())


def _read_worktree_include(repo_root: Path) -> list[str]:
    path = repo_root / ".worktreeinclude"
    if not path.is_file():
        return []
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


async def _list_ignored_files(repo_root: Path) -> list[Path]:
    output = await _run_git(
        repo_root,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "--directory",
    )
    result: list[Path] = []
    excluded = (repo_root / ".Licode" / "worktrees").resolve()
    for value in output.splitlines():
        candidate = (repo_root / value.rstrip("/")).resolve()
        if candidate == excluded or excluded in candidate.parents:
            continue
        if candidate.is_dir():
            result.extend(path for path in candidate.rglob("*") if path.is_file())
        elif candidate.is_file():
            result.append(candidate)
    return result


async def copy_included_ignored(repo_root: Path, wt_path: Path) -> None:
    patterns = _read_worktree_include(repo_root)
    if not patterns:
        return
    for source in await _list_ignored_files(repo_root):
        relative = source.relative_to(repo_root)
        rendered = relative.as_posix()
        if not any(
            fnmatch.fnmatch(rendered, pattern) or fnmatch.fnmatch(relative.name, pattern)
            for pattern in patterns
        ):
            continue
        target = wt_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


async def _perform_post_creation_setup(
    repo_root: Path,
    wt_path: Path,
    symlink_dirs: list[str],
) -> None:
    steps: tuple[tuple[str, Callable[[], object | Awaitable[object]]], ...] = (
        ("本地配置", lambda: copy_local_configs(repo_root, wt_path)),
        ("Git hooks", lambda: setup_git_hooks(repo_root, wt_path)),
        ("软链", lambda: symlink_large_dirs(repo_root, wt_path, symlink_dirs)),
        ("ignored 文件", lambda: copy_included_ignored(repo_root, wt_path)),
    )
    for name, operation in steps:
        try:
            result = operation()
            if hasattr(result, "__await__"):
                await result  # type: ignore[misc]
        except (OSError, RuntimeError, ValueError) as exc:
            _warn(name, exc)


async def create_worktree(
    manager: Manager,
    name: str,
    base_ref: str,
    manual: bool,
) -> Worktree:
    validate_slug(name)
    async with manager.lock:
        if name in manager.active or name in manager._pending_names or name in manager._busy_names:
            raise ValueError(f"Worktree 已存在: {name}")
        manager._pending_names.add(name)

    flat = flat_slug(name)
    wt_path = Path(manager.worktree_dir) / flat
    branch = f"worktree-{flat}"
    try:
        if wt_path.exists():
            head_sha = _resolve_head_sha_from_fs(wt_path)
            if not head_sha:
                raise ValueError(f"已有目录不是有效 Worktree: {wt_path}")
            initial_sha = _resolve_initial_head_sha_from_fs(wt_path)
            worktree = Worktree(
                name=name,
                path=str(wt_path.resolve()),
                branch=branch,
                based_on=initial_sha or head_sha,
                # 缺少 reflog 时不能证明目录没有创建后新增的提交，保守地禁止自动删除。
                head_commit=initial_sha or "",
                created=datetime.fromtimestamp(wt_path.stat().st_mtime),
                manual=manual,
            )
        else:
            try:
                await _run_git(
                    manager.repo_root,
                    "worktree",
                    "add",
                    "-B",
                    branch,
                    str(wt_path),
                    base_ref,
                )
            except (OSError, RuntimeError):
                shutil.rmtree(wt_path, ignore_errors=True)
                raise
            await _perform_post_creation_setup(
                Path(manager.repo_root), wt_path, manager.symlink_dirs
            )
            head_sha = await _run_git(wt_path, "rev-parse", "HEAD")
            worktree = Worktree(
                name=name,
                path=str(wt_path.resolve()),
                branch=branch,
                based_on=base_ref,
                head_commit=head_sha,
                created=datetime.now(),
                manual=manual,
            )
        async with manager.lock:
            manager.active[name] = worktree
        return worktree
    finally:
        async with manager.lock:
            manager._pending_names.discard(name)
