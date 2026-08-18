import asyncio
import json
import threading
from collections.abc import AsyncIterator
from pathlib import Path

import yaml

from Licode.llm import Message, Request, StreamEvent
from Licode.memory import Manager, Store, UpdateAction


class FakeProvider:
    def __init__(self, response: str) -> None:
        self.response = response
        self.requests: list[Request] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        yield StreamEvent(text=self.response)
        yield StreamEvent(done=True)


def _frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---\n", 2)[1])


def test_store_create_update_delete_note(tmp_path: Path) -> None:
    store = Store(str(tmp_path))
    create = UpdateAction(
        action="create",
        level="project",
        type="project_knowledge",
        title="接口约定",
        slug="api_rules",
        content="使用 REST。",
    )
    store.apply([create])
    path = tmp_path / "project_knowledge_api_rules.md"
    assert path.is_file()
    assert _frontmatter(path)["type"] == "project_knowledge"
    assert "接口约定" in store.load_index()

    created = _frontmatter(path)["created"]
    store.apply(
        [
            UpdateAction(
                action="update",
                level="project",
                filename=path.name,
                title="新接口约定",
                content="使用 JSON API。",
            )
        ]
    )
    assert "使用 JSON API。" in path.read_text(encoding="utf-8")
    assert _frontmatter(path)["created"] == created
    assert "新接口约定" in store.load_index()

    store.apply([UpdateAction(action="delete", level="project", filename=path.name)])
    assert not path.exists()
    assert "新接口约定" not in store.load_index()


def test_manager_load_index_project_first_and_truncates(tmp_path: Path) -> None:
    project = tmp_path / "project"
    user = tmp_path / "user"
    project.mkdir()
    user.mkdir()
    (project / "MEMORY.md").write_text("项目索引", encoding="utf-8")
    (user / "MEMORY.md").write_text("用户索引", encoding="utf-8")
    manager = Manager(str(project), str(user), None, "")
    assert manager.load_index() == "项目索引\n\n用户索引"

    (project / "MEMORY.md").write_text("中" * 30000, encoding="utf-8")
    index = manager.load_index()
    assert len(index.encode("utf-8")) <= 25 * 1024
    assert index.endswith("(index truncated)")


async def test_manager_update_async_parses_response_without_tools(tmp_path: Path) -> None:
    response = json.dumps(
        [
            {
                "action": "create",
                "level": "user",
                "type": "user_preference",
                "title": "简洁回复",
                "slug": "terse_replies",
                "content": "用户偏好简洁回复。",
            }
        ],
        ensure_ascii=False,
    )
    provider = FakeProvider(response)
    manager = Manager(str(tmp_path / "project"), str(tmp_path / "user"), provider, "fake")

    await manager.update_async([Message(role="user", content="记住简洁回复")])

    assert (tmp_path / "user" / "user_preference_terse_replies.md").is_file()
    assert provider.requests[0].tools is None
    assert "记住简洁回复" in provider.requests[0].messages[0].content


def test_store_concurrent_apply_keeps_all_notes(tmp_path: Path) -> None:
    store = Store(str(tmp_path))
    barrier = threading.Barrier(11)

    def create(index: int) -> None:
        barrier.wait()
        store.apply(
            [
                UpdateAction(
                    action="create",
                    level="project",
                    type="project_knowledge",
                    title=f"标题 {index}",
                    slug=f"note_{index}",
                    content=f"内容 {index}",
                )
            ]
        )

    threads = [threading.Thread(target=create, args=(index,)) for index in range(10)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()

    assert len(list(tmp_path.glob("project_knowledge_note_*.md"))) == 10
    assert len(store.load_index().splitlines()) == 10


async def test_manager_serializes_concurrent_updates(tmp_path: Path) -> None:
    provider = FakeProvider("[]")
    manager = Manager(str(tmp_path / "project"), str(tmp_path / "user"), provider, "fake")
    await asyncio.gather(
        manager.update_async([Message(role="user", content="a")]),
        manager.update_async([Message(role="user", content="b")]),
    )
    assert len(provider.requests) == 2
