"""用真实 provider 连续请求两轮并打印缓存用量。"""

import asyncio
from pathlib import Path

from Licode import config
from Licode.agent import Agent, SessionRuntime
from Licode.compact import (
    CompactCircuitBreaker,
    ContentReplacementState,
    RecoveryState,
    new_session_context,
)
from Licode.config import effective_context_window
from Licode.conversation import Conversation
from Licode.llm import new_provider
from Licode.permission import Mode, new_engine
from Licode.tool import new_default_registry


async def _run_turn(agent: Agent, conversation: Conversation, text: str) -> None:
    conversation.add_user(text)
    async for event in agent.run(conversation, Mode.BYPASS, asyncio.Event()):
        if event.text:
            print(event.text, end="", flush=True)
        if event.usage is not None:
            usage = event.usage
            print(
                f"\nusage: input={usage.input} output={usage.output} "
                f"cache_write={usage.cache_write} cache_read={usage.cache_read}"
            )
        if event.err is not None:
            print(f"\nerror: {event.err}")
    print()


async def main() -> None:
    settings = config.load(".Licode/config.yaml")
    provider = new_provider(settings.providers[0])
    engine, _ = new_engine(str(Path.cwd().resolve()))
    runtime = SessionRuntime(
        replacement=ContentReplacementState(),
        recovery=RecoveryState(),
        auto_tracking=CompactCircuitBreaker(),
        session=new_session_context(str(Path.cwd())),
        context_window=effective_context_window(settings.providers[0]),
    )
    agent = Agent(provider, new_default_registry(), "dev", engine, runtime=runtime)
    conversation = Conversation()
    await _run_turn(agent, conversation, "请用一句话介绍你自己。")
    await _run_turn(agent, conversation, "请再用一句话概括你的工作方式。")


if __name__ == "__main__":
    asyncio.run(main())
