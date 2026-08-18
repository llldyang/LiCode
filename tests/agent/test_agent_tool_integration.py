import json

import pytest

from Licode.agent import AgentTool
from Licode.llm import StreamEvent
from Licode.subagent import load_catalog
from Licode.task import Manager

from .test_run_to_completion import FakeProvider, agent_for


@pytest.mark.asyncio
async def test_defined_subagent_runs_with_filtered_tools(tmp_path) -> None:
    provider = FakeProvider([[StreamEvent(text="探索完成")]])
    parent = agent_for(tmp_path, provider)
    manager = Manager()
    tool = AgentTool(load_catalog(str(tmp_path)), manager, parent, True)
    result = await tool.execute(
        json.dumps({"prompt": "查看项目", "description": "探索", "subagent_type": "Explore"})
    )
    assert result.content == "探索完成"
    tool_names = [item.name for item in provider.requests[0].tools or []]
    assert "Agent" not in tool_names
    assert "write_file" not in tool_names
    assert "edit_file" not in tool_names
