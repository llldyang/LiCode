import pytest

from Licode.permission.matcher import compile_matcher


@pytest.mark.parametrize(
    ("pattern", "value", "matched"),
    [
        pytest.param("=git status", "git status", True, id="exact-hit"),
        pytest.param("=git status", "git status -s", False, id="exact-miss"),
        pytest.param("~^npm (install|test)$", "npm install", True, id="regex-hit"),
        pytest.param("~^npm (install|test)$", "npm run dev", False, id="regex-miss"),
        pytest.param("!=foo", "foo", False, id="not-exact-miss"),
        pytest.param("!=foo", "bar", True, id="not-exact-hit"),
        pytest.param("!~^rm", "rm -rf .", False, id="not-regex-miss"),
        pytest.param("!~^rm", "ls -lh", True, id="not-regex-hit"),
        pytest.param("!git *", "git status", False, id="not-glob-miss"),
        pytest.param("!git *", "npm install", True, id="not-glob-hit"),
        pytest.param("src/**", "src/a/b.py", True, id="path-double-star"),
        pytest.param("src/*", "src/a/b.py", False, id="path-single-star"),
    ],
)
def test_matcher_types(pattern: str, value: str, matched: bool) -> None:
    matcher = compile_matcher(pattern, is_command=not pattern.startswith("src/"))
    assert matcher.match(value) is matched


@pytest.mark.parametrize("pattern", ["", "~[invalid", "!"])
def test_invalid_matcher(pattern: str) -> None:
    with pytest.raises(ValueError):
        compile_matcher(pattern, is_command=False)
