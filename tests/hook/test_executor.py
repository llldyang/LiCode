import json
import subprocess
import sys

import httpx
import pytest

from Licode.hook import Event
from Licode.hook.executor import Executor
from Licode.hook.rule import (
    Action,
    ActionType,
    HttpAction,
    PromptAction,
    Rule,
    ShellAction,
    SubagentAction,
)


def command(script: str) -> str:
    return subprocess.list2cmdline([sys.executable, "-c", script])


def shell_rule(script: str, *, timeout: float = 30) -> Rule:
    return Rule(
        "shell-test",
        Event.PRE_TOOL_USE,
        Action(ActionType.SHELL, shell=ShellAction(command(script))),
        timeout_s=timeout,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("script", "blocked", "has_error"),
    [
        ("import sys; print('blocked', file=sys.stderr); sys.exit(2)", True, False),
        ("raise SystemExit(0)", False, False),
        ("import sys; print('failed', file=sys.stderr); sys.exit(1)", False, True),
    ],
)
async def test_shell_exit_semantics(script: str, blocked: bool, has_error: bool) -> None:
    executor = Executor()
    result = await executor.run(shell_rule(script), {"z": 1, "a": 2}, blocking=True)
    assert result.blocked is blocked
    assert (result.err is not None) is has_error
    if blocked:
        assert result.reason == "blocked"
    await executor.close()


@pytest.mark.asyncio
async def test_shell_stdin_json_has_stable_key_order(tmp_path) -> None:
    output = tmp_path / "payload.json"
    script = (
        f"import pathlib,sys; pathlib.Path({str(output)!r}).write_bytes(sys.stdin.buffer.read())"
    )
    executor = Executor()
    result = await executor.run(shell_rule(script), {"z": 1, "a": 2}, blocking=False)
    assert result.err is None
    assert output.read_text(encoding="utf-8") == '{"a": 2, "z": 1}'
    await executor.close()


@pytest.mark.asyncio
async def test_shell_timeout() -> None:
    executor = Executor()
    result = await executor.run(
        shell_rule("import time; time.sleep(2)", timeout=0.05),
        {},
        blocking=False,
    )
    assert isinstance(result.err, TimeoutError)
    await executor.close()


@pytest.mark.asyncio
async def test_prompt_and_subagent_stub(capsys: pytest.CaptureFixture[str]) -> None:
    executor = Executor()
    prompt = Rule(
        "prompt",
        Event.SESSION_START,
        Action(ActionType.PROMPT, prompt=PromptAction("use zh-CN")),
    )
    subagent = Rule(
        "sub",
        Event.SESSION_START,
        Action(
            ActionType.SUBAGENT,
            subagent=SubagentAction("reviewer", "review this"),
        ),
    )
    assert (await executor.run(prompt, {}, blocking=False)).prompt == "use zh-CN"
    assert not (await executor.run(subagent, {}, blocking=False)).blocked
    assert "[hook subagent] not yet implemented, skipped: reviewer" in capsys.readouterr().err
    await executor.close()


@pytest.mark.asyncio
async def test_http_block_template_and_failure() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/fail":
            return httpx.Response(500, json={"error": "x"})
        return httpx.Response(200, json={"decision": "block", "reason": "network policy"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    executor = Executor(client)
    action = Action(
        ActionType.HTTP,
        http=HttpAction("https://hooks.test/check", body="{event}"),
    )
    result = await executor.run(
        Rule("http", Event.PRE_TOOL_USE, action),
        {"event": "PreToolUse"},
        blocking=True,
    )
    assert result.blocked and result.reason == "network policy"
    assert requests[0].content == b"PreToolUse"

    failed_action = Action(
        ActionType.HTTP,
        http=HttpAction("https://hooks.test/fail"),
    )
    failed = await executor.run(
        Rule("http-fail", Event.STOP, failed_action),
        {"event": "Stop"},
        blocking=False,
    )
    assert failed.err is not None and not failed.blocked
    await client.aclose()


@pytest.mark.asyncio
async def test_http_default_body_is_sorted_json() -> None:
    body = b""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal body
        body = request.content
        return httpx.Response(200, json={"decision": "allow"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    executor = Executor(client)
    action = Action(ActionType.HTTP, http=HttpAction("https://hooks.test/done"))
    result = await executor.run(Rule("http", Event.STOP, action), {"z": 1, "a": 2}, blocking=False)
    assert result.err is None
    assert json.loads(body) == {"a": 2, "z": 1}
    assert body == b'{"a": 2, "z": 1}'
    await client.aclose()
