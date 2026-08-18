"""向会话注入固定提示词的内置命令。"""

from Licode import prompt
from Licode.permission import Mode

from .ui import UI

REVIEW_DIRECTIVE = "请审查当前上下文中的代码变更/已读取的文件，指出潜在 bug、可读性问题和可简化处。"


async def handle_do(ui: UI) -> None:
    ui.set_mode(Mode.DEFAULT)
    ui.inject_and_send("/do", prompt.EXECUTE_DIRECTIVE)


async def handle_review(ui: UI) -> None:
    ui.inject_and_send("/review", REVIEW_DIRECTIVE)
