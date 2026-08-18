from pathlib import Path

from Licode.instructions import Loader


def test_three_layers_load_in_priority_order(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (tmp_path / "LiCode.md").write_text("项目根", encoding="utf-8")
    (tmp_path / ".Licode").mkdir()
    (tmp_path / ".Licode" / "LiCode.md").write_text("项目配置", encoding="utf-8")
    (home / ".Licode").mkdir(parents=True)
    (home / ".Licode" / "LiCode.md").write_text("用户配置", encoding="utf-8")

    output = Loader(str(tmp_path), str(home)).load()

    assert output == "项目根\n\n项目配置\n\n用户配置"


def test_missing_and_empty_files_are_silent(tmp_path: Path) -> None:
    (tmp_path / "LiCode.md").write_text("", encoding="utf-8")
    assert Loader(str(tmp_path), str(tmp_path / "home")).load() == ""


def test_include_expands_nested_files_and_keeps_inline_text(tmp_path: Path) -> None:
    rules = tmp_path / "rules"
    rules.mkdir()
    (tmp_path / "LiCode.md").write_text(
        "开头\n@include rules/a.md\n段落中的 @include rules/a.md 保留\n",
        encoding="utf-8",
    )
    (rules / "a.md").write_text("A\n@include b.md\n", encoding="utf-8")
    (rules / "b.md").write_text("B", encoding="utf-8")

    output = Loader(str(tmp_path), str(tmp_path / "home")).load()

    assert "开头\nA\nB\n段落中的 @include rules/a.md 保留" == output


def test_include_depth_is_limited_to_five_levels(tmp_path: Path) -> None:
    for index in range(1, 7):
        content = f"@include {index + 1}.md" if index < 6 else "第六层"
        (tmp_path / f"{index}.md").write_text(content, encoding="utf-8")
    (tmp_path / "LiCode.md").write_text("@include 1.md", encoding="utf-8")

    output = Loader(str(tmp_path), str(tmp_path / "home")).load()

    assert "第六层" not in output
    assert "超过最大嵌套深度" in output


def test_include_loop_escape_and_binary_are_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.md"
    outside.write_text("不应读取", encoding="utf-8")
    (tmp_path / "binary.md").write_bytes(b"abc\x00def")
    (tmp_path / "loop.md").write_text("@include LiCode.md", encoding="utf-8")
    (tmp_path / "LiCode.md").write_text(
        "@include loop.md\n@include ../outside.md\n@include binary.md",
        encoding="utf-8",
    )

    output = Loader(str(tmp_path), str(tmp_path / "home")).load()

    assert "检测到环路" in output
    assert "路径超出允许范围" in output
    assert "二进制文件不可读" in output
    assert "不应读取" not in output
