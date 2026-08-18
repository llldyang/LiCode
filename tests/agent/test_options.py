import pytest

from Licode.agent import Agent
from Licode.conversation import Conversation
from Licode.llm import StreamEvent
from Licode.permission import Mode

from .test_run_to_completion import FakeProvider, agent_for


@pytest.mark.asyncio
async def test_agent_options_affect_request(tmp_path) -> None:
    provider = FakeProvider([[StreamEvent(text="ok")]])
    agent = agent_for(
        tmp_path,
        provider,
        system_prompt="角色系统提示",
        max_turns=9,
        permission_mode=Mode.PLAN,
        dont_ask=True,
        allowed_tools=["read_file"],
        is_sub_agent=True,
    )
    assert isinstance(agent, Agent)
    assert agent.max_turns == 9
    assert agent.permission_mode is Mode.PLAN
    assert agent.dont_ask
    assert agent.is_sub_agent
    assert await agent.run_to_completion(Conversation(), "任务") == "ok"
    request = provider.requests[0]
    assert request.system.stable == "角色系统提示"
    assert [tool.name for tool in request.tools or []] == ["read_file"]
