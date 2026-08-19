"""Team 邮箱与第 13 章后台续派共用的 SendMessage 工具。"""

from __future__ import annotations

import json
import time
from typing import Any

from Licode.agent.team_hook import teammate_context_from_ctx
from Licode.conversation import Conversation
from Licode.session import load_session
from Licode.task import RUNNING
from Licode.team.backend import new_backend
from Licode.team.mailbox import Box, Message, MessageType
from Licode.team.types import BackendType
from Licode.tool import Result

from .team_create import _object, _optional_text, _required_text


class SendMessageTool:
    read_only = False
    is_system = False

    def __init__(self, manager, fallback=None) -> None:
        self.manager = manager
        self.fallback = fallback

    def name(self) -> str:
        return "SendMessage"

    def description(self) -> str:
        return "向 Team 成员发消息或续派已完成的后台 SubAgent。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "to": {"type": "string"},
                "summary": {"type": "string"},
                "message": {"type": "string"},
                "type": {"type": "string", "enum": [item.value for item in MessageType]},
                "payload": {"type": "object"},
                "name": {"type": "string"},
            },
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        try:
            value = _object(args)
            if "to" not in value:
                if self.fallback is None:
                    raise ValueError("to 必填")
                return await self.fallback.execute(args)
            team = self.manager.current_team()
            context = teammate_context_from_ctx()
            sender = context.member_name if context is not None else "lead"
            to = _required_text(value, "to")
            message_type_raw = value.get("type", MessageType.TEXT.value)
            if not isinstance(message_type_raw, str):
                raise ValueError("type 必须是字符串")
            message_type = MessageType(message_type_raw)
            summary = _optional_text(value, "summary")
            content = _optional_text(value, "message")
            payload = value.get("payload")
            if payload is not None and not isinstance(payload, dict):
                raise ValueError("payload 必须是对象")
            if message_type is MessageType.TEXT and not summary:
                raise ValueError("text 消息必须提供 summary")
            if message_type is MessageType.PLAN_APPROVAL_RESPONSE and sender != "lead":
                raise ValueError("只有 Lead 可以发送 plan_approval_response")
            if message_type is MessageType.SHUTDOWN_RESPONSE and to != "lead":
                raise ValueError("shutdown_response 只能发给 Lead")

            if to == "*":
                targets = [member for member in team.members if member.name != sender]
            else:
                # agent_id 是 Team 内的稳定标识，不能因其他 Team 的同名成员覆盖注册表而失效。
                target = team.member_by_agent_id(to)
                if target is None:
                    agent_id = self.manager.registry.resolve(to)
                    target = team.member_by_agent_id(agent_id or "") or team.member_by_name(to)
                if target is None:
                    raise ValueError(f"当前 Team 中找不到收件人: {to}")
                targets = [target]
            if not targets:
                raise ValueError("没有可投递的 Team 成员")

            timestamp = int(time.time())
            delivered: list[str] = []
            box = Box(team.mailbox_dir)
            for target in targets:
                await box.write(
                    target.agent_id,
                    Message(
                        from_=sender,
                        to=target.name,
                        type=message_type,
                        summary=summary,
                        content=content,
                        payload=payload,
                        timestamp=timestamp,
                    ),
                )
                backend = new_backend(target.backend_type, task_mgr=self.manager.task_mgr)
                if target.backend_type is not BackendType.IN_PROCESS:
                    await backend.wake(target.pane_id, target.agent_id)
                elif target.name != "lead":
                    task = self.manager.task_mgr.get(target.agent_id)
                    if task is not None and task.status is not RUNNING:
                        writer = self.manager._session_writers.get(target.agent_id)
                        if target.session_dir:
                            # 磁盘会话是续派的事实来源，避免长期空闲后沿用陈旧的内存快照。
                            task.conv = Conversation.from_messages(
                                load_session(target.session_dir),
                                on_append=writer.on_append if writer is not None else None,
                                on_replace=writer.on_replace if writer is not None else None,
                            )
                        await team.set_member_active(target.name, True)
                        await self.manager.task_mgr.send_message(target.name, content)
                delivered.append(target.agent_id)
            return Result(
                json.dumps({"delivered_to": delivered, "timestamp": timestamp}, ensure_ascii=False)
            )
        except Exception as exc:
            return Result(str(exc), is_error=True)
