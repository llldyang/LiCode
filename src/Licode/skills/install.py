"""从受支持 URL 安装目录型 Skill。"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from .catalog import Catalog
from .parser import SkillParseError, parse_skill_dir
from .types import SkillSource

MAX_FILE_SIZE = 1 * 1024 * 1024
MAX_TOTAL_SIZE = 8 * 1024 * 1024
MAX_FILE_COUNT = 64
MAX_RECURSION_DEPTH = 4


class SkillInstallError(RuntimeError):
    """远程 Skill 地址、内容或安装过程不合法。"""


@dataclass(frozen=True, slots=True)
class SkillURL:
    owner: str
    repo: str
    ref: str
    path: str


def _segments(path: str) -> list[str]:
    return [segment for segment in path.split("/") if segment]


def parse_skill_url(url: str) -> SkillURL:
    parsed = urlparse(url)
    host = parsed.netloc.casefold()
    parts = _segments(parsed.path)
    if parsed.scheme != "https":
        raise SkillInstallError("Skill URL 必须使用 https")

    if host == "github.com":
        if len(parts) < 5 or parts[2] != "tree":
            raise SkillInstallError("GitHub URL 必须是 /owner/repo/tree/ref/path")
        owner, repo, _, ref, *path_parts = parts
    elif host == "raw.githubusercontent.com":
        if len(parts) < 5:
            raise SkillInstallError("raw GitHub URL 缺少 owner/repo/ref/path")
        owner, repo, ref, *path_parts = parts
        if path_parts[-1].casefold() == "skill.md":
            path_parts.pop()
    elif host == "skills.sh":
        if len(parts) < 3:
            raise SkillInstallError("skills.sh URL 必须是 /owner/repo/path")
        owner, repo, *path_parts = parts
        ref = "main"
    else:
        raise SkillInstallError(f"不支持的 Skill URL host: {parsed.netloc}")

    if not owner or not repo or not ref or not path_parts:
        raise SkillInstallError("Skill URL 缺少仓库、版本或目录")
    return SkillURL(owner=owner, repo=repo, ref=ref, path="/".join(path_parts))


def _safe_relative(root_path: str, item_path: str) -> Path:
    if "\\" in item_path:
        raise SkillInstallError(f"GitHub API 返回非法路径: {item_path}")
    root = PurePosixPath(root_path)
    item = PurePosixPath(item_path)
    try:
        relative = item.relative_to(root)
    except ValueError as exc:
        raise SkillInstallError(f"GitHub API 返回越界路径: {item_path}") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise SkillInstallError(f"GitHub API 返回非法路径: {item_path}")
    return Path(*relative.parts)


async def _response_json(client: httpx.AsyncClient, url: str) -> Any:
    try:
        response = await client.get(url)
    except httpx.HTTPError as exc:
        raise SkillInstallError(f"GitHub API 请求失败: {exc}") from exc
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise SkillInstallError(f"GitHub API 请求失败: {response.status_code}") from exc
    try:
        return response.json()
    except ValueError as exc:
        raise SkillInstallError("GitHub API 返回了无效 JSON") from exc


async def _download_tree(
    client: httpx.AsyncClient,
    source: SkillURL,
    staging: Path,
) -> None:
    file_count = 0
    total_size = 0

    async def walk(api_path: str, depth: int) -> None:
        nonlocal file_count, total_size
        if depth > MAX_RECURSION_DEPTH:
            raise SkillInstallError(f"Skill 目录深度超过 {MAX_RECURSION_DEPTH}")
        encoded_path = quote(api_path, safe="/")
        url = (
            f"https://api.github.com/repos/{source.owner}/{source.repo}/contents/"
            f"{encoded_path}?ref={quote(source.ref, safe='')}"
        )
        payload = await _response_json(client, url)
        entries = payload if isinstance(payload, list) else [payload]
        if not all(isinstance(entry, dict) for entry in entries):
            raise SkillInstallError("GitHub Contents API 返回结构无效")

        for entry in sorted(entries, key=lambda item: str(item.get("path", ""))):
            item_type = entry.get("type")
            item_path = entry.get("path")
            if not isinstance(item_path, str):
                raise SkillInstallError("GitHub API 条目缺少 path")
            relative = _safe_relative(source.path, item_path)
            # 同时校验 API 返回的真实相对层级，防止服务端把深层文件直接塞进浅层响应。
            item_depth = len(relative.parts) if item_type == "dir" else len(relative.parts) - 1
            if item_depth > MAX_RECURSION_DEPTH:
                raise SkillInstallError(f"Skill 目录深度超过 {MAX_RECURSION_DEPTH}")
            if item_type == "dir":
                await walk(item_path, depth + 1)
                continue
            if item_type != "file":
                raise SkillInstallError(f"Skill 包含不支持的条目类型: {item_type}")

            file_count += 1
            if file_count > MAX_FILE_COUNT:
                raise SkillInstallError(f"Skill 文件数超过 {MAX_FILE_COUNT}")
            declared_size = entry.get("size", 0)
            if not isinstance(declared_size, int) or declared_size < 0:
                raise SkillInstallError(f"GitHub API 文件大小无效: {item_path}")
            if declared_size > MAX_FILE_SIZE:
                raise SkillInstallError(f"单文件超过 {MAX_FILE_SIZE} 字节: {item_path}")
            download_url = entry.get("download_url")
            if not isinstance(download_url, str) or not download_url:
                raise SkillInstallError(f"文件缺少下载地址: {item_path}")

            try:
                response = await client.get(download_url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise SkillInstallError(f"Skill 文件下载失败: {item_path}") from exc
            content = response.content
            if len(content) > MAX_FILE_SIZE:
                raise SkillInstallError(f"单文件超过 {MAX_FILE_SIZE} 字节: {item_path}")
            total_size += len(content)
            if total_size > MAX_TOTAL_SIZE:
                raise SkillInstallError(f"Skill 总大小超过 {MAX_TOTAL_SIZE} 字节")
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

    await walk(source.path, 0)


def _replace_directory(staging: Path, destination: Path) -> None:
    backup = destination.with_name(destination.name + ".backup")
    if backup.exists():
        shutil.rmtree(backup)
    if destination.exists():
        destination.replace(backup)
    try:
        staging.replace(destination)
    except Exception:
        if backup.exists() and not destination.exists():
            backup.replace(destination)
        raise
    if backup.exists():
        shutil.rmtree(backup)


async def install_from_url(
    source_url: str,
    catalog: Catalog,
    work_dir: Path,
    *,
    install_root: Path | None = None,
) -> str:
    source = parse_skill_url(source_url)
    root = install_root or (Path.home() / ".Licode" / "skills")
    root.mkdir(parents=True, exist_ok=True)
    temporary_parent = Path(tempfile.mkdtemp(prefix=".Licode-skill-", dir=root.parent))
    staging = temporary_parent / "skill"
    staging.mkdir()
    try:
        timeout = httpx.Timeout(60.0)
        headers = {"Accept": "application/vnd.github+json"}
        async with httpx.AsyncClient(
            timeout=timeout,
            headers=headers,
            follow_redirects=True,
        ) as client:
            await _download_tree(client, source, staging)
        if not (staging / "SKILL.md").is_file():
            raise SkillInstallError("远程目录不含 SKILL.md")
        try:
            skill = parse_skill_dir(staging, SkillSource.USER)
        except SkillParseError as exc:
            raise SkillInstallError(f"远程 SKILL.md 无效: {exc}") from exc
        destination = root / skill.name
        _replace_directory(staging, destination)
        catalog.reload(work_dir)
        return skill.name
    finally:
        if temporary_parent.exists():
            shutil.rmtree(temporary_parent, ignore_errors=True)


# spec 使用 install_skill 名称。
install_skill = install_from_url
