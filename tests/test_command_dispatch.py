import pytest

from Licode.command import parse, parse_with_args


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ("", False)),
        ("   ", ("", False)),
        ("hello", ("", False)),
        ("/", ("", True)),
        ("/help", ("help", True)),
        ("  /HELP  ", ("help", True)),
        ("/help xx", ("", True)),
        ("/help  ", ("help", True)),
        ("//double", ("/double", True)),
        ("/ /help", ("", True)),
    ],
)
def test_parse(value: str, expected: tuple[str, bool]) -> None:
    assert parse(value) == expected


def test_parse_with_args() -> None:
    assert parse_with_args("/worktree create feature/a") == (
        "worktree",
        "create feature/a",
        True,
    )
    assert parse_with_args("hello") == ("", "", False)
