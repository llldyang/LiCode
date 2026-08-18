from collections.abc import AsyncIterator

import pytest

from Licode.agent.launch import ForkLaunchOpts, launch_fork
from Licode.conversation import Conversation
from Licode.llm import Request, StreamEvent
from Licode.permission import new_engine
from Licode.tool import new_default_registry


class FakeProvider:
    name = "fake"
    model = "fake"

    def __init__(self) -> None:
        self.requests: list[Request] = []

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        yield StreamEvent(text="fork done")


@pytest.mark.asyncio
async def test_launch_fork_runs_preloaded_conversation(tmp_path) -> None:
    provider = FakeProvider()
    engine, error = new_engine(str(tmp_path))
    assert error is None
    conversation = Conversation()
    conversation.add_user("已装填任务")
    result = await launch_fork(
        ForkLaunchOpts(
            allowed_tools=["read_file"],
            model="inherit",
            conv=conversation,
            system_prompt="fork system",
            background=False,
            events_sink=None,
            provider=provider,
            registry=new_default_registry(),
            engine=engine,
            version="test",
            hook_engine=None,
        )
    )
    assert result == "fork done"
    assert provider.requests[0].messages[0].content == "已装填任务"
    assert provider.requests[0].system.stable == "fork system"
