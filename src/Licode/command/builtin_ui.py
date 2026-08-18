"""修改终端界面或会话状态的内置命令。"""

from Licode.permission import Mode

from .ui import UI


async def handle_exit(ui: UI) -> None:
    ui.quit()


async def handle_plan(ui: UI) -> None:
    ui.set_mode(Mode.PLAN)
    ui.println("已切换到 PLAN 模式")


async def handle_compact(ui: UI) -> None:
    if not ui.idle():
        ui.error("请等待当前任务完成")
        return
    ui.force_compact()


async def handle_resume(ui: UI) -> None:
    if not ui.idle():
        ui.error("请等待当前任务完成")
        return
    ui.open_resume_menu()


async def handle_clear(ui: UI) -> None:
    ui.clear_and_new_session()
    ui.println("已清空当前会话，开启新 session")
