"""LiCode 命令行入口。"""

import sys

from Licode import config
from Licode.config import ConfigError
from Licode.tui import LiCodeApp


def main() -> None:
    try:
        cfg = config.load(".Licode/config.yaml")
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None

    try:
        app = LiCodeApp(cfg.providers)
        app.run(inline=True, inline_no_clear=True)
        app.print_transcript()
    except KeyboardInterrupt:
        return
    except Exception as exc:
        print(f"LiCode 启动失败: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
