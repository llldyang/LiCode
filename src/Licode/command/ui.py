"""命令处理函数可访问的最小 UI 协议。"""

from typing import Protocol

from Licode.hook.rule import Rule as HookRule
from Licode.permission import Mode
from Licode.skills import SkillSummary


class UI(Protocol):
    def println(self, msg: str) -> None: ...

    def error(self, msg: str) -> None: ...

    def mode(self) -> Mode: ...

    def set_mode(self, mode: Mode) -> None: ...

    def inject_and_send(self, display_label: str, preset_prompt: str) -> None: ...

    def usage_in(self) -> int: ...

    def usage_out(self) -> int: ...

    def model_name(self) -> str: ...

    def cwd(self) -> str: ...

    def tool_count(self) -> int: ...

    def memory_files(self) -> list[str]: ...

    def session_path(self) -> str: ...

    def session_id(self) -> str: ...

    def quit(self) -> None: ...

    def force_compact(self) -> None: ...

    def open_resume_menu(self) -> None: ...

    def clear_and_new_session(self) -> None: ...

    def idle(self) -> bool: ...

    def list_catalog_skills(self) -> list[SkillSummary]: ...

    def list_active_skills(self) -> list[str]: ...

    def clear_active_skills(self) -> None: ...

    def append_assistant_message(self, text: str) -> None: ...

    def hook_sources(self) -> list[str]: ...

    def hook_rules(self) -> list[HookRule]: ...


class NopUI:
    """供命令单元测试使用的无副作用 UI。"""

    def println(self, msg: str) -> None:
        del msg

    def error(self, msg: str) -> None:
        del msg

    def mode(self) -> Mode:
        return Mode.DEFAULT

    def set_mode(self, mode: Mode) -> None:
        del mode

    def inject_and_send(self, display_label: str, preset_prompt: str) -> None:
        del display_label, preset_prompt

    def usage_in(self) -> int:
        return 0

    def usage_out(self) -> int:
        return 0

    def model_name(self) -> str:
        return ""

    def cwd(self) -> str:
        return ""

    def tool_count(self) -> int:
        return 0

    def memory_files(self) -> list[str]:
        return []

    def session_path(self) -> str:
        return ""

    def session_id(self) -> str:
        return ""

    def quit(self) -> None:
        return None

    def force_compact(self) -> None:
        return None

    def open_resume_menu(self) -> None:
        return None

    def clear_and_new_session(self) -> None:
        return None

    def idle(self) -> bool:
        return True

    def list_catalog_skills(self) -> list[SkillSummary]:
        return []

    def list_active_skills(self) -> list[str]:
        return []

    def clear_active_skills(self) -> None:
        return None

    def append_assistant_message(self, text: str) -> None:
        del text

    def hook_sources(self) -> list[str]:
        return []

    def hook_rules(self) -> list[HookRule]:
        return []
