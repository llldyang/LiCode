import pytest

from Licode.team.backend import SpawnRequest
from Licode.team.backend.tmux import TmuxBackend, build_member_cmd


def test_member_command_contains_identity_without_prompt() -> None:
    request = SpawnRequest(
        team_name="demo",
        member_name="alice",
        agent_id="agent-123",
        worktree_path="/repo/.Licode/worktrees/team-demo+alice",
        session_dir="/repo/.Licode/sessions/session-1",
        agent_type="general-purpose",
        model="sonnet",
        initial_prompt="不能出现在命令行里的长任务",
        plan_mode_required=True,
    )
    command = build_member_cmd(request)
    assert command[1:3] == ["-m", "Licode"]
    assert command[command.index("--agent-id") + 1] == "agent-123"
    assert command[command.index("--agent-type") + 1] == "general-purpose"
    assert "--plan-mode" in command
    assert request.initial_prompt not in command


@pytest.mark.asyncio
async def test_spawn_outside_tmux_passes_one_shell_command(monkeypatch) -> None:
    request = SpawnRequest(
        "demo",
        "alice",
        "agent-123",
        "/repo/wt",
        "/repo/session",
        "general-purpose",
        "",
        "不能出现在命令行",
        False,
    )
    calls: list[tuple[str, ...]] = []

    async def fake_run(*args: str, check: bool = True) -> str:
        del check
        calls.append(args)
        return "%1\n"

    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.setattr("Licode.team.backend.tmux._run_tmux", fake_run)

    assert await TmuxBackend().spawn(request) == ("%1", "agent-123")
    assert calls[0][:5] == ("new-session", "-d", "-P", "-F", "#{pane_id}")
    assert len(calls[0]) == 6
    assert "--agent-id agent-123" in calls[0][-1]
    assert request.initial_prompt not in calls[0][-1]
