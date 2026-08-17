"""LiCode 命令行入口。"""

import sys
from pathlib import Path

from Licode import __version__, config, permission
from Licode.config import ConfigError
from Licode.tool import new_default_registry
from Licode.tui import new_app


def main() -> None:
    try:
        cfg = config.load(".Licode/config.yaml")
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None

    try:
        registry = new_default_registry()
        engine, engine_error = permission.new_engine(str(Path.cwd().resolve()))
        if engine_error is not None:
            print(f"权限引擎降级: {engine_error}", file=sys.stderr)
        app = new_app(cfg.providers, __version__, registry, engine)
        app.run(inline=True, inline_no_clear=True)
        app.print_transcript()
    except KeyboardInterrupt:
        return
    except Exception as exc:
        print(f"LiCode 启动失败: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
