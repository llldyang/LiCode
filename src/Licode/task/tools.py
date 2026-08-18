"""供主 Agent 查询和控制后台任务的四个系统工具。"""

from __future__ import annotations

import json
from typing import Any

from Licode.tool import Result

from .manager import BackgroundTask, Manager


def _arguments(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"参数不是有效 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("参数必须是 JSON 对象")
    return value


def _brief(task: BackgroundTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "name": task.name,
        "status": str(task.status),
        "tool_count": task.tool_count,
        "last_activity": task.last_activity,
    }


def _full(task: BackgroundTask) -> dict[str, Any]:
    return {
        **_brief(task),
        "task": task.task,
        "result": task.result,
        "err": str(task.err) if task.err is not None else "",
        "start_time": task.start_time,
        "end_time": task.end_time,
        "usage": {
            "input": task.usage.input,
            "output": task.usage.output,
            "cache_write": task.usage.cache_write,
            "cache_read": task.usage.cache_read,
        },
    }


class _TaskTool:
    read_only = True
    is_system = True

    def __init__(self, manager: Manager) -> None:
        self.manager = manager


class TaskListTool(_TaskTool):
    def name(self) -> str:
        return "TaskList"

    def description(self) -> str:
        return "列出当前进程中的后台 SubAgent 任务。"

    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}, "additionalProperties": False}

    async def execute(self, args: str) -> Result:
        try:
            _arguments(args)
        except ValueError as exc:
            return Result(str(exc), is_error=True)
        payload = [_brief(task) for task in self.manager.list()]
        return Result(json.dumps(payload, ensure_ascii=False))


class TaskGetTool(_TaskTool):
    def name(self) -> str:
        return "TaskGet"

    def description(self) -> str:
        return "读取指定后台任务的完整状态。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        try:
            task_id = str(_arguments(args).get("task_id") or "")
        except ValueError as exc:
            return Result(str(exc), is_error=True)
        task = self.manager.get(task_id)
        if task is None:
            return Result(f"unknown task_id: {task_id}", is_error=True)
        return Result(json.dumps(_full(task), ensure_ascii=False))


class TaskStopTool(_TaskTool):
    def name(self) -> str:
        return "TaskStop"

    def description(self) -> str:
        return "取消指定的后台 SubAgent 任务。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        try:
            task_id = str(_arguments(args).get("task_id") or "")
        except ValueError as exc:
            return Result(str(exc), is_error=True)
        if not await self.manager.stop(task_id):
            return Result(f"unknown task_id: {task_id}", is_error=True)
        return Result(json.dumps({"status": "cancellation_requested"}))


class SendMessageTool(_TaskTool):
    def name(self) -> str:
        return "SendMessage"

    def description(self) -> str:
        return "给已完成且有名称的后台 SubAgent 续派任务。"

    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["name", "message"],
            "additionalProperties": False,
        }

    async def execute(self, args: str) -> Result:
        try:
            values = _arguments(args)
            name = str(values.get("name") or "")
            message = str(values.get("message") or "")
            if not name or not message:
                raise ValueError("name 和 message 不能为空")
            task_id = await self.manager.send_message(name, message)
        except Exception as exc:
            return Result(str(exc), is_error=True)
        return Result(json.dumps({"task_id": task_id, "status": "resumed"}))
