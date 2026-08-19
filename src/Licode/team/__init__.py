"""Agent Team 数据、后端与协作能力。"""

from .backend import Backend, SpawnRequest, new_backend
from .backend.detect import detect
from .mailbox import Box, Message, MessageType
from .manager import LeadMessage, Manager
from .persistence import atomic_write_json, read_json, sanitize
from .registry import AgentNameRegistry
from .types import (
    BackendType,
    InProcessTeammateNoSpawnError,
    MemberExistsError,
    MemberNotFoundError,
    Team,
    TeamError,
    TeamHasActiveMembersError,
    TeammateInfo,
    TeamNotFoundError,
)

__all__ = [
    "AgentNameRegistry",
    "Backend",
    "BackendType",
    "Box",
    "InProcessTeammateNoSpawnError",
    "LeadMessage",
    "Manager",
    "MemberExistsError",
    "MemberNotFoundError",
    "Message",
    "MessageType",
    "SpawnRequest",
    "Team",
    "TeamError",
    "TeamHasActiveMembersError",
    "TeamNotFoundError",
    "TeammateInfo",
    "atomic_write_json",
    "detect",
    "new_backend",
    "read_json",
    "sanitize",
]
