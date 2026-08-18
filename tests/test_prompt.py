from pathlib import Path

from Licode import prompt
from Licode.prompt import Environment, Module
from Licode.tool import new_default_registry


def test_modules_are_ordered_and_extend_without_changing_assembler() -> None:
    assembled = prompt.assemble_system(
        [Module("末尾", 30, "third"), Module("开头", 10, "first"), Module("中间", 20, "second")]
    )

    assert assembled == "first\n\nsecond\n\nthird"
    stable = prompt.build_system_prompt()
    assert stable.index("You are LiCode") < stable.index("read_file, glob, and grep")


def test_empty_optional_modules_are_skipped_without_extra_blank_lines() -> None:
    assembled = prompt.assemble_system(
        [Module("一", 10, "one"), Module("空", 20, ""), Module("二", 30, "two")]
    )

    assert assembled == "one\n\ntwo"
    assert all(module.content == "" for module in prompt.optional_modules())


def test_instructions_and_memory_fill_optional_modules_in_priority_order() -> None:
    stable = prompt.build_system_prompt("PROJECT RULE", "REMEMBER THIS")

    assert "PROJECT RULE" in stable
    assert "REMEMBER THIS" in stable
    assert stable.index("PROJECT RULE") < stable.index("REMEMBER THIS")
    assert prompt.build_system_prompt("", "") == prompt.build_system_prompt()


def test_stable_system_is_deterministic_and_contains_tool_rules() -> None:
    first = prompt.build_system_prompt()
    second = prompt.build_system_prompt()
    definitions = {item.name: item.description for item in new_default_registry().definitions()}

    assert first == second
    assert "Prefer the dedicated read_file, glob, and grep" in first
    assert "Before editing a file, you must first read it with read_file" in first
    assert "编辑前请先用 read_file" in definitions["edit_file"]
    assert "优先用 read_file/glob/grep" in definitions["bash"]


def test_environment_render_and_non_git_fallback(tmp_path: Path, monkeypatch) -> None:
    environment = Environment(
        working_dir="C:/work",
        platform="win32",
        date="2026-08-17",
        git_status="2 changed file(s)",
        version="0.1.0",
        model="test-model",
    )
    rendered = environment.render()

    for value in (
        "C:/work",
        "win32",
        "2026-08-17",
        "2 changed file(s)",
        "0.1.0",
        "test-model",
    ):
        assert value in rendered

    monkeypatch.chdir(tmp_path)
    gathered = prompt.gather_environment("dev", "fake")
    assert gathered.working_dir == str(tmp_path)
    assert gathered.git_status == ""
    assert gathered.date
    assert gathered.platform


def test_system_and_plan_reminders_are_tagged_and_have_two_detail_levels() -> None:
    wrapped = prompt.system_reminder("补充指令")
    full = prompt.plan_reminder(True)
    concise = prompt.plan_reminder(False)

    assert wrapped == "<system-reminder>\n补充指令\n</system-reminder>"
    assert full.startswith("<system-reminder>") and full.endswith("</system-reminder>")
    assert "/do" in full
    assert len(full) > len(concise)
