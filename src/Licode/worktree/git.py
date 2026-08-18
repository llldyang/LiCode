"""Worktree 使用的 Git 子进程和只读恢复辅助函数。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path


async def _run_git(work_dir: str | Path, *args: str) -> str:
    """在指定目录运行非交互 Git 命令。"""

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_ASKPASS"] = ""
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(work_dir),
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"git {' '.join(args)} 执行失败")
    return stdout.decode("utf-8", errors="replace").rstrip("\r\n")


async def _has_worktree_changes(wt_path: str | Path, base_commit: str) -> bool:
    """检测未提交修改或创建后新增的提交；检测失败时保守地保留。"""

    try:
        if await _run_git(wt_path, "status", "--porcelain"):
            return True
        count = await _run_git(wt_path, "rev-list", "--count", f"{base_commit}..HEAD")
        return int(count or "0") > 0
    except (OSError, RuntimeError, ValueError):
        return True


def _git_dir_from_worktree(wt_path: str | Path) -> Path | None:
    pointer = Path(wt_path) / ".git"
    try:
        if pointer.is_dir():
            return pointer.resolve()
        raw = pointer.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    prefix = "gitdir:"
    if not raw.lower().startswith(prefix):
        return None
    value = raw[len(prefix) :].strip()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = pointer.parent / candidate
    return candidate.resolve()


def _common_git_dir(git_dir: Path) -> Path:
    try:
        raw = (git_dir / "commondir").read_text(encoding="utf-8").strip()
    except OSError:
        return git_dir
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = git_dir / candidate
    return candidate.resolve()


def _read_packed_ref(common_dir: Path, ref_name: str) -> str | None:
    try:
        lines = (common_dir / "packed-refs").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        if not line or line.startswith(("#", "^")):
            continue
        sha, _, name = line.partition(" ")
        if name == ref_name and sha:
            return sha
    return None


def _resolve_head_sha_from_fs(wt_path: str | Path) -> str | None:
    """只读 .git 指针、HEAD 和 refs 恢复 Worktree 的 HEAD。"""

    git_dir = _git_dir_from_worktree(wt_path)
    if git_dir is None:
        return None
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not head.startswith("ref: "):
        return head or None
    ref_name = head.removeprefix("ref: ").strip()
    common_dir = _common_git_dir(git_dir)
    for root in (git_dir, common_dir):
        try:
            value = (root / ref_name).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return _read_packed_ref(common_dir, ref_name)
