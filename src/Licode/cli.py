"""LiCode 命令行入口。"""

import asyncio
import os
import sys

from Licode import __version__, config, permission
from Licode import mcp as mcp_client
from Licode.config import ConfigError
from Licode.tool import new_default_registry
from Licode.tui import new_app


async def _amain() -> int:
    try:
        cfg = config.load(".Licode/config.yaml")
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 1

    try:
        root = os.getcwd()
        registry = new_default_registry()
        mcp_config = mcp_client.load_config(root)
        manager = await mcp_client.new_manager(mcp_config, version=__version__)
        try:
            for external_tool in manager.tools():
                registry.register(external_tool)
            engine, engine_error = permission.new_engine(root)
            if engine_error is not None:
                print(f"权限引擎降级: {engine_error}", file=sys.stderr)
            app = new_app(cfg.providers, __version__, registry, engine)
            await app.run_async(inline=True, inline_no_clear=True)
            app.print_transcript()
        finally:
            await manager.close()
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"LiCode 启动失败: {exc}", file=sys.stderr)
        return 1
    return 0


def main() -> None:
    try:
        code = asyncio.run(_amain())
    except KeyboardInterrupt:
        code = 0
    raise SystemExit(code)
