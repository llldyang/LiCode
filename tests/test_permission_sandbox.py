from pathlib import Path
from types import SimpleNamespace

import pytest

from Licode.permission.sandbox import eval_symlinks_or_ancestor, resolve_root, sandbox_ok


def test_sandbox_accepts_inside_and_new_nested_paths(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    engine = SimpleNamespace(root=resolve_root(str(root)))

    assert sandbox_ok(engine, str(root / "existing.txt"))
    assert sandbox_ok(engine, str(root / "new" / "nested" / "file.txt"))
    resolved = eval_symlinks_or_ancestor(str(root / "new" / "nested" / "file.txt"))
    assert resolved.endswith(str(Path("new") / "nested" / "file.txt"))


def test_sandbox_rejects_parent_escape(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    engine = SimpleNamespace(root=resolve_root(str(root)))

    assert not sandbox_ok(engine, "../outside.txt")
    assert not sandbox_ok(engine, str(tmp_path / "outside.txt"))


def test_sandbox_resolves_symlink_before_prefix_check(tmp_path: Path) -> None:
    root = tmp_path / "project"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("当前 Windows 环境不允许创建符号链接")
    engine = SimpleNamespace(root=resolve_root(str(root)))

    assert not sandbox_ok(engine, str(link / "secret.txt"))
