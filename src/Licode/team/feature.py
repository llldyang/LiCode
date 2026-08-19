"""Team 相关 feature flag。"""

from typing import Any


def fork_teammate_enabled(config: Any) -> bool:
    features = getattr(config, "features", None)
    return bool(getattr(features, "fork_teammate", False))


__all__ = ["fork_teammate_enabled"]
