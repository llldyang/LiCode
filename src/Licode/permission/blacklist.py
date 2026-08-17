"""启发式、非完备且不可由配置放开的危险命令黑名单。"""

import re
from collections.abc import Iterable

_BLACKLIST: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE | re.DOTALL)
    for pattern in (
        r"(?:^|[;&|]\s*)rm\s+(?:-[a-z]*[rf][a-z]*\s+)+(?:/|~|\$HOME)(?:\*|/\*)?(?:\s|$)",
        r"\bdd\b.*\bof\s*=\s*/dev/",
        r":\s*\(\s*\)\s*\{.*:\s*\|\s*:\s*&.*\}\s*;\s*:",
        r"\bmkfs(?:\.[a-z0-9_-]+)?\b",
        r">\s*/dev/(?:sd|hd|nvme|disk)",
        r"\bchmod\s+-R\s+0?777\s+/(?:\s|$)",
    )
)


def patterns() -> tuple[re.Pattern[str], ...]:
    """返回只读的内置黑名单正则集合。"""

    return _BLACKLIST


def hits_blacklist(command: str, blacklist: Iterable[re.Pattern[str]] = _BLACKLIST) -> bool:
    return any(pattern.search(command) is not None for pattern in blacklist)
