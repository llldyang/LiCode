import pytest

from Licode.command import Command, Kind, NopUI, Registry


async def noop(ui: NopUI) -> None:
    del ui


def command(name: str, *, aliases: list[str] | None = None, hidden: bool = False) -> Command:
    return Command(name, f"{name} description", Kind.LOCAL, noop, aliases or [], hidden)


def test_register_ok_and_lookup_alias_case_insensitive() -> None:
    registry = Registry()
    item = command("help", aliases=["h"])

    registry.register(item)

    assert registry.lookup("HELP") is item
    assert registry.lookup("H") is item
    assert registry.lookup("missing") is None


def test_register_duplicate_name_raises_with_conflict() -> None:
    registry = Registry()
    registry.register(command("help"))

    with pytest.raises(RuntimeError, match="help"):
        registry.register(command("help"))


def test_register_duplicate_alias_raises_with_conflict() -> None:
    registry = Registry()
    registry.register(command("help", aliases=["h"]))

    with pytest.raises(RuntimeError, match="h"):
        registry.register(command("history", aliases=["h"]))


def test_register_rejects_duplicate_key_inside_one_command_atomically() -> None:
    registry = Registry()

    with pytest.raises(RuntimeError, match="help"):
        registry.register(command("help", aliases=["help"]))

    assert registry.lookup("help") is None


@pytest.mark.parametrize("name", ["", "Help"])
def test_register_rejects_invalid_name(name: str) -> None:
    with pytest.raises(ValueError):
        Registry().register(command(name))


def test_visible_sorted_returns_copy_and_hides_hidden_commands() -> None:
    registry = Registry()
    registry.register(command("status"))
    registry.register(command("secret", hidden=True))
    registry.register(command("help"))

    visible = registry.visible()
    visible.clear()

    assert [item.name for item in registry.visible()] == ["help", "status"]
    assert registry.lookup("secret") is not None


def test_prefix_match_uses_only_visible_primary_names() -> None:
    registry = Registry()
    registry.register(command("session", aliases=["status-alias"]))
    registry.register(command("status"))
    registry.register(command("secret", hidden=True))

    assert [item.name for item in registry.prefix_match("/s")] == ["session", "status"]
    assert registry.prefix_match("/status-a") == []
    assert [item.name for item in registry.prefix_match("/")] == ["session", "status"]
