"""LiCode 命令行入口。"""

import sys

from Licode import __version__, config
from Licode.config import ConfigError
from Licode.tool import new_default_registry
from Licode.tui import LiCodeApp


def main() -> None:
    try:
        cfg = config.load(".Licode/config.yaml")
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None

    try:
        registry = new_default_registry()
        app = LiCodeApp(cfg.providers, __version__, registry)
        app.run(inline=True, inline_no_clear=True)
        app.print_transcript()
    except KeyboardInterrupt:
        return
    except Exception as exc:
        print(f"LiCode 启动失败: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
