"""两级记忆索引与异步 LLM 更新编排。"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from pathlib import Path

from Licode.llm import Message, Provider, Request, System

from .prompts import MEMORY_UPDATE_SYSTEM_PROMPT
from .store import Store
from .types import UpdateAction

logger = logging.getLogger(__name__)
MAX_INDEX_BYTES = 25 * 1024
TRUNCATED_MARKER = "(index truncated)"


class Manager:
    def __init__(
        self,
        project_dir: str,
        user_dir: str,
        provider: Provider | None,
        model: str,
    ) -> None:
        self.project_store = Store(project_dir)
        self.user_store = Store(user_dir)
        self._provider = provider
        self._model = model
        self._lock = asyncio.Lock()

    def load_index(self) -> str:
        project = self.project_store.load_index().strip()
        user = self.user_store.load_index().strip()
        combined = "\n\n".join(part for part in (project, user) if part)
        encoded = combined.encode("utf-8")
        if len(encoded) <= MAX_INDEX_BYTES:
            return combined
        marker = ("\n" + TRUNCATED_MARKER).encode("utf-8")
        prefix = encoded[: MAX_INDEX_BYTES - len(marker)]
        while True:
            try:
                text = prefix.decode("utf-8")
                break
            except UnicodeDecodeError:
                prefix = prefix[:-1]
        return text + marker.decode("utf-8")

    def set_provider(self, provider: Provider, model: str) -> None:
        self._provider = provider
        self._model = model

    def list_files(self) -> tuple[list[str], list[str]]:
        """按项目层、用户层返回已加载目录中的 Markdown 文件名。"""

        return self._list_store_files(self.project_store.dir), self._list_store_files(
            self.user_store.dir
        )

    @staticmethod
    def _list_store_files(directory: str) -> list[str]:
        path = Path(directory)
        try:
            return sorted(
                item.name for item in path.iterdir() if item.is_file() and item.suffix == ".md"
            )
        except FileNotFoundError:
            return []
        except OSError as exc:
            logger.warning("列出记忆文件失败 %s: %s", path, exc)
            return []

    async def update_async(self, recent_msgs: list[Message]) -> None:
        async with self._lock:
            try:
                provider = self._provider
                if provider is None:
                    return
                payload = {
                    "model": self._model,
                    "project_index": self.project_store.load_index(),
                    "user_index": self.user_store.load_index(),
                    "recent_messages": [asdict(message) for message in recent_msgs],
                }
                request = Request(
                    messages=[
                        Message(
                            role="user",
                            content=json.dumps(payload, ensure_ascii=False),
                        )
                    ],
                    tools=None,
                    system=System(stable=MEMORY_UPDATE_SYSTEM_PROMPT),
                )
                parts: list[str] = []
                async for event in provider.stream(request):
                    if event.err is not None:
                        raise event.err
                    if event.text:
                        parts.append(event.text)
                raw = json.loads("".join(parts))
                if not isinstance(raw, list):
                    raise ValueError("记忆更新响应必须是 JSON 数组")
                actions = [UpdateAction(**item) for item in raw if isinstance(item, dict)]
                project_actions = [item for item in actions if item.level == "project"]
                user_actions = [item for item in actions if item.level == "user"]
                if project_actions:
                    await asyncio.to_thread(self.project_store.apply, project_actions)
                if user_actions:
                    await asyncio.to_thread(self.user_store.apply, user_actions)
            except Exception:
                logger.exception("自动记忆更新失败")
