from pathlib import Path

from Licode.memory import Manager


def manager(project: Path, user: Path) -> Manager:
    return Manager(str(project), str(user), provider=None, model="")


def test_list_files_with_missing_directories(tmp_path: Path) -> None:
    assert manager(tmp_path / "project", tmp_path / "user").list_files() == ([], [])


def test_list_files_includes_memory_index(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "MEMORY.md").write_text("index", encoding="utf-8")

    assert manager(project, tmp_path / "user").list_files() == (["MEMORY.md"], [])


def test_list_files_sorts_multiple_markdown_files(tmp_path: Path) -> None:
    project = tmp_path / "project"
    user = tmp_path / "user"
    project.mkdir()
    user.mkdir()
    for name in ("z.md", "MEMORY.md", "a.md"):
        (project / name).write_text(name, encoding="utf-8")
    for name in ("user.md", "MEMORY.md"):
        (user / name).write_text(name, encoding="utf-8")

    assert manager(project, user).list_files() == (
        ["MEMORY.md", "a.md", "z.md"],
        ["MEMORY.md", "user.md"],
    )


def test_list_files_ignores_non_markdown_and_directories(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "note.md").write_text("note", encoding="utf-8")
    (project / "note.txt").write_text("note", encoding="utf-8")
    (project / "nested.md").mkdir()

    assert manager(project, tmp_path / "user").list_files() == (["note.md"], [])
