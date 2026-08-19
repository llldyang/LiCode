from Licode.team import AgentNameRegistry


def test_registry_resolve_reverse_and_overwrite() -> None:
    registry = AgentNameRegistry()
    registry.register("alice", "agent-1")
    assert registry.resolve("alice") == "agent-1"
    assert registry.resolve("agent-1") == "agent-1"
    assert registry.name_of("agent-1") == "alice"

    registry.register("alice", "agent-2")
    assert registry.resolve("agent-1") is None
    assert registry.name_of("agent-2") == "alice"

    registry.register("bob", "agent-2")
    assert registry.resolve("alice") is None
    assert registry.list_() == {"bob": "agent-2"}
