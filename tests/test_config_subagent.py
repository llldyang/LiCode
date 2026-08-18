from pathlib import Path

import pytest

from Licode.config import ConfigError, load

BASE = """providers:
  - name: test
    protocol: openai
    api_key: key
    model: model
"""


def test_subagent_background_defaults_true(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(BASE, encoding="utf-8")
    assert load(str(path)).effective_enable_subagent_background()


def test_subagent_background_can_be_disabled(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(BASE + "enable_subagent_background: false\n", encoding="utf-8")
    assert not load(str(path)).effective_enable_subagent_background()


def test_subagent_background_rejects_non_bool(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(BASE + "enableSubAgentBackground: nope\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load(str(path))
