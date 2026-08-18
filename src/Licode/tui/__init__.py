"""LiCode 终端界面。"""

from Licode.agent import SessionRuntime
from Licode.config import ProviderConfig
from Licode.memory import Manager as MemoryManager
from Licode.permission import Engine
from Licode.session import Writer
from Licode.tool import Registry

from .app import LiCodeApp, SessionState


def new_app(
    providers: list[ProviderConfig],
    version: str,
    registry: Registry,
    engine: Engine,
    runtime: SessionRuntime | None = None,
    writer: Writer | None = None,
    memory_manager: MemoryManager | None = None,
    instruction_text: str = "",
    memory_text: str = "",
    sessions_dir: str | None = None,
) -> LiCodeApp:
    return LiCodeApp(
        providers,
        version,
        registry,
        engine,
        runtime,
        writer,
        memory_manager,
        instruction_text,
        memory_text,
        sessions_dir,
    )


__all__ = ["LiCodeApp", "SessionState", "new_app"]
