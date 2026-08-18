from pathlib import Path

import pytest

from Licode.config import ConfigError, ProviderConfig, effective_context_window, load


def write_config(tmp_path: Path, content: str) -> str:
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return str(path)


def test_load_valid_config(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """providers:
  - name: Claude
    protocol: anthropic
    api_key: secret
    model: claude-test
    thinking: true
  - name: Compatible
    protocol: openai
    api_key: secret-2
    model: model-test
    base_url: https://example.invalid/v1
""",
    )

    config = load(path)

    assert len(config.providers) == 2
    assert config.providers[0].thinking is True
    assert config.providers[1].base_url == "https://example.invalid/v1"


@pytest.mark.parametrize("field", ["name", "api_key", "model"])
def test_missing_required_field(tmp_path: Path, field: str) -> None:
    values = {
        "name": "Claude",
        "protocol": "anthropic",
        "api_key": "secret",
        "model": "claude-test",
    }
    values.pop(field)
    body = "\n".join(f"    {key}: {value}" for key, value in values.items())
    path = write_config(tmp_path, f"providers:\n  -\n{body}\n")

    with pytest.raises(ConfigError, match=rf"providers\[0\]\.{field} 不能为空"):
        load(path)


def test_invalid_protocol(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """providers:
  - name: Unknown
    protocol: other
    api_key: secret
    model: test
""",
    )

    with pytest.raises(ConfigError, match="protocol 必须是"):
        load(path)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="配置文件不存在"):
        load(str(tmp_path / "missing.yaml"))


def test_invalid_yaml(tmp_path: Path) -> None:
    path = write_config(tmp_path, "providers: [")
    with pytest.raises(ConfigError, match="YAML 格式错误"):
        load(path)


def test_context_window_load_and_protocol_defaults(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """providers:
  - name: Claude
    protocol: anthropic
    api_key: secret
    model: claude-test
    context_window: 80000
""",
    )
    provider = load(path).providers[0]
    assert provider.context_window == 80000
    assert effective_context_window(provider) == 80000
    assert effective_context_window(ProviderConfig("Claude", "anthropic", "key", "model")) == 200000
    assert (
        effective_context_window(
            ProviderConfig("OpenAI", "openai", "key", "model", context_window=0)
        )
        == 128000
    )
    unknown = ProviderConfig("Unknown", "other", "key", "model")
    assert effective_context_window(unknown) == 200000


def test_context_window_must_be_integer(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """providers:
  - name: Claude
    protocol: anthropic
    api_key: secret
    model: claude-test
    context_window: wide
""",
    )
    with pytest.raises(ConfigError, match="context_window 必须是整数"):
        load(path)


def test_config_example_can_be_loaded() -> None:
    config = load(".Licode/config.yaml.example")
    assert config.providers[0].context_window == 200000
