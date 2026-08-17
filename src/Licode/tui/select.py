"""Provider 选择列表的辅助函数。"""

from textual.widgets.option_list import Option

from Licode.config import ProviderConfig


def provider_options(providers: list[ProviderConfig]) -> list[Option]:
    return [
        Option(f"{provider.name} ({provider.model})", id=str(index))
        for index, provider in enumerate(providers)
    ]


def provider_at(providers: list[ProviderConfig], option_id: str | None) -> ProviderConfig:
    if option_id is None:
        raise ValueError("未选择 provider")
    return providers[int(option_id)]
