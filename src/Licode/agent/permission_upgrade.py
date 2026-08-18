"""子 Agent 权限请求升级到宿主界面的回调协议。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from Licode.permission import Outcome

if TYPE_CHECKING:
    from . import ApprovalRequest

ApprovalUpgrader = Callable[["ApprovalRequest"], Awaitable[tuple[Outcome, bool]]]
