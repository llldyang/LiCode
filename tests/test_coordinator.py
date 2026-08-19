from types import SimpleNamespace

from Licode.coordinator import allowed_tools, env_truthy, is_enabled, system_prompt_suffix


def test_coordinator_requires_feature_and_environment(monkeypatch) -> None:
    disabled = SimpleNamespace(features=SimpleNamespace(coordinator_mode=False))
    enabled = SimpleNamespace(features=SimpleNamespace(coordinator_mode=True))
    monkeypatch.delenv("MEWCODE_COORDINATOR_MODE", raising=False)
    monkeypatch.delenv("LICODE_COORDINATOR_MODE", raising=False)
    assert is_enabled(disabled) is False
    assert is_enabled(enabled) is False
    monkeypatch.setenv("MEWCODE_COORDINATOR_MODE", "yes")
    assert is_enabled(disabled) is False
    assert is_enabled(enabled) is True


def test_coordinator_policy_and_truthy_values() -> None:
    tools = allowed_tools()
    assert "bash" in tools
    assert "write_file" not in tools
    assert "edit_file" not in tools
    assert all(env_truthy(value) for value in ("1", "TRUE", " yes "))
    assert "派出 Agent" in system_prompt_suffix()
    assert "TaskList" in system_prompt_suffix()
