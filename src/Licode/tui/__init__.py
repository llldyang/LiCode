"""LiCode 终端界面。"""

from Licode.agent import SessionRuntime
from Licode.config import ProviderConfig
from Licode.permission import Engine
from Licode.tool import Registry

from .app import LiCodeApp, SessionState


def new_app(
    providers: list[ProviderConfig],
    version: str,
    registry: Registry,
    engine: Engine,
    runtime: SessionRuntime | None = None,
) -> LiCodeApp:
    return LiCodeApp(providers, version, registry, engine, runtime)


__all__ = ["LiCodeApp", "SessionState", "new_app"]
