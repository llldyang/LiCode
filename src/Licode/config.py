"""LiCode 的 YAML 配置加载与校验。"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from Licode.protocol_defaults import (
    DEFAULT_ANTHROPIC_CONTEXT_WINDOW,
    DEFAULT_OPENAI_CONTEXT_WINDOW,
)


class ConfigError(Exception):
    """配置无法读取或不满足约束。"""


@dataclass
class ProviderConfig:
    name: str
    protocol: Literal["anthropic", "openai"]
    api_key: str
    model: str
    base_url: str | None = None
    thinking: bool = False
    context_window: int = 0


@dataclass
class Config:
    providers: list[ProviderConfig] = field(default_factory=list)


def _required_text(item: dict[str, Any], field_name: str, index: int) -> str:
    value = item.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"providers[{index}].{field_name} 不能为空")
    return value.strip()


def _from_dict(raw: Any) -> Config:
    if not isinstance(raw, dict):
        raise ConfigError("配置根节点必须是映射")

    providers = raw.get("providers")
    if not isinstance(providers, list) or not providers:
        raise ConfigError("providers 必须是非空列表")

    result: list[ProviderConfig] = []
    for index, item in enumerate(providers):
        if not isinstance(item, dict):
            raise ConfigError(f"providers[{index}] 必须是映射")

        name = _required_text(item, "name", index)
        protocol = _required_text(item, "protocol", index)
        if protocol not in {"anthropic", "openai"}:
            raise ConfigError(f"providers[{index}].protocol 必须是 anthropic 或 openai")

        api_key = _required_text(item, "api_key", index)
        model = _required_text(item, "model", index)
        base_url = item.get("base_url")
        if base_url is not None and (not isinstance(base_url, str) or not base_url.strip()):
            raise ConfigError(f"providers[{index}].base_url 必须是非空字符串")
        thinking = item.get("thinking", False)
        if not isinstance(thinking, bool):
            raise ConfigError(f"providers[{index}].thinking 必须是布尔值")
        context_window = item.get("context_window", 0)
        if isinstance(context_window, bool) or not isinstance(context_window, int):
            raise ConfigError(f"providers[{index}].context_window 必须是整数")

        result.append(
            ProviderConfig(
                name=name,
                protocol=cast(Literal["anthropic", "openai"], protocol),
                api_key=api_key,
                model=model,
                base_url=base_url.strip() if isinstance(base_url, str) else None,
                thinking=thinking,
                context_window=context_window,
            )
        )
    return Config(providers=result)


def load(path: str) -> Config:
    """从指定 YAML 文件加载并校验配置。"""

    config_path = Path(path)
    try:
        content = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ConfigError(f"配置文件不存在: {path}") from exc
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {path}: {exc}") from exc

    try:
        raw = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML 格式错误: {exc}") from exc
    return _from_dict(raw)


def effective_context_window(provider: ProviderConfig) -> int:
    """返回显式配置或当前协议的默认上下文窗口。"""

    if provider.context_window > 0:
        return provider.context_window
    if provider.protocol == "openai":
        return DEFAULT_OPENAI_CONTEXT_WINDOW
    return DEFAULT_ANTHROPIC_CONTEXT_WINDOW
