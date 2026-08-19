import asyncio
import json
import threading
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest

from Licode.agent import Agent, ApprovalRequest
from Licode.command import NopUI, register_builtins
from Licode.command import Registry as CommandRegistry
from Licode.command.builtin_skill import handle_skill
from Licode.command.skills import register_skills_as_commands, remove_skill_commands
from Licode.config import ProviderConfig
from Licode.conversation import Conversation
from Licode.llm import Request, StreamEvent, ToolCall
from Licode.permission import Engine, Mode
from Licode.prompt import (
    ActiveSkillEntry,
    SkillCatalogItem,
    render_active_skills_block,
    render_skills_catalog,
)
from Licode.skills import (
    ActiveSkills,
    Catalog,
    Executor,
    SkillDependencyError,
    SkillInstallError,
    SkillParseError,
    SkillSource,
    SkillSummary,
    filter_tool_registry,
    install_from_url,
    parse_frontmatter,
    parse_skill_dir,
    parse_skill_file,
    parse_skill_url,
    render_body,
    substitute_arguments,
)
from Licode.skills.install import _download_tree, _replace_directory, _safe_relative
from Licode.tool import Registry as ToolRegistry
from Licode.tool import Result, new_default_registry
from Licode.tool.install_skill import InstallSkillTool
from Licode.tool.load_skill import LoadSkillTool


class FakeProvider:
    def __init__(self, scripts: list[list[StreamEvent]]) -> None:
        self.scripts = scripts
        self.requests: list[Request] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def model(self) -> str:
        return "fake-model"

    async def stream(self, request: Request) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        for event in self.scripts[len(self.requests) - 1]:
            await asyncio.sleep(0)
            yield event


class DummyTool:
    read_only = True
    is_system = False
    is_system_tool = False

    def __init__(self, tool_name: str) -> None:
        self._name = tool_name

    def name(self) -> str:
        return self._name

    def description(self) -> str:
        return self._name

    def parameters(self) -> dict[str, object]:
        return {"type": "object"}

    async def execute(self, args: str) -> Result:
        return Result(args)


class SystemTool(DummyTool):
    is_system = True
    is_system_tool = True


class RecordingUI(NopUI):
    def __init__(self) -> None:
        self.printed: list[str] = []
        self.errors: list[str] = []
        self.injections: list[tuple[str, str]] = []
        self.assistant_messages: list[str] = []
        self.catalog_skills: list[SkillSummary] = []
        self.active_skill_names: list[str] = []

    def println(self, msg: str) -> None:
        self.printed.append(msg)

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def inject_and_send(self, display_label: str, preset_prompt: str) -> None:
        self.injections.append((display_label, preset_prompt))

    def append_assistant_message(self, text: str) -> None:
        self.assistant_messages.append(text)

    def list_catalog_skills(self) -> list[SkillSummary]:
        return list(self.catalog_skills)

    def list_active_skills(self) -> list[str]:
        return list(self.active_skill_names)


def write_skill(
    root: Path,
    name: str,
    body: str = "执行 $ARGUMENTS",
    *,
    description: str = "测试 Skill",
    mode: str = "inline",
    context: str = "none",
    allowed_tools: list[str] | None = None,
    directory: bool = True,
    model: str | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    target = root / name / "SKILL.md" if directory else root / f"{name}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"name: {name}",
        f"description: {description}",
        f"mode: {mode}",
        f"fork_context: {context}",
    ]
    if allowed_tools is not None:
        lines.append("allowed_tools:")
        lines.extend(f"  - {tool}" for tool in allowed_tools)
    if model is not None:
        lines.append(f"model: {model}")
    lines.extend(("---", "", body))
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def isolated_catalog(work_dir: Path, user_dir: Path | None = None) -> Catalog:
    catalog = Catalog(work_dir)
    catalog._user_dir = user_dir or work_dir / "user-skills"
    catalog.reload()
    return catalog


def permission_engine(root: Path) -> Engine:
    return Engine(
        root=str(root.resolve()),
        local_path=str(root / ".Licode" / "settings.local.yaml"),
    )


def provider_config(name: str = "fake", model: str = "fake-model") -> ProviderConfig:
    return ProviderConfig(name=name, protocol="openai", api_key="test", model=model)


def test_parser_reads_frontmatter_file_and_directory(tmp_path: Path) -> None:
    skill_path = write_skill(
        tmp_path,
        "review-code",
        "检查 $ARGUMENTS",
        mode="fork",
        context="recent",
        allowed_tools=["read_file", "grep", "grep"],
        model="review-model",
    )

    meta, body = parse_frontmatter(skill_path.read_text(encoding="utf-8"))
    skill = parse_skill_dir(skill_path.parent, SkillSource.PROJECT)

    assert meta["name"] == "review-code"
    assert body == "检查 $ARGUMENTS"
    assert skill.name == "review-code"
    assert skill.description == "测试 Skill"
    assert skill.allowed_tools == ["read_file", "grep"]
    assert skill.mode == "fork"
    assert skill.context == "recent"
    assert skill.model == "review-model"
    assert skill.source_path == skill_path.resolve()
    assert skill.is_directory


@pytest.mark.parametrize(
    "raw",
    [
        "name: no-frontmatter",
        "---\nname: open",
        "---\n[\n---\nbody",
        "---\n- item\n---\nbody",
        "---\ndescription: missing name\n---\nbody",
        "---\nname: missing-description\n---\nbody",
        "---\nname: Invalid_Name\ndescription: bad\n---\nbody",
        "---\nname: bad-mode\ndescription: bad\nmode: other\n---\nbody",
        "---\nname: bad-context\ndescription: bad\ncontext: other\n---\nbody",
    ],
)
def test_parser_rejects_invalid_frontmatter(tmp_path: Path, raw: str) -> None:
    path = tmp_path / "bad.md"
    path.write_text(raw, encoding="utf-8")

    with pytest.raises(SkillParseError):
        parse_skill_file(path, SkillSource.PROJECT)


def test_parser_reports_missing_and_invalid_utf8_files(tmp_path: Path) -> None:
    with pytest.raises(SkillParseError, match="不存在"):
        parse_skill_file(tmp_path / "missing.md", SkillSource.PROJECT)

    invalid = tmp_path / "invalid.md"
    invalid.write_bytes(b"\xff\xfe")
    with pytest.raises(SkillParseError, match="无法读取"):
        parse_skill_file(invalid, SkillSource.PROJECT)


@pytest.mark.parametrize(
    "metadata",
    [
        "allowed_tools: read_file",
        "allowed_tools: [read_file, 1]",
        "model: ''",
        "model: 1",
    ],
)
def test_parser_rejects_invalid_allowed_tools_and_model(tmp_path: Path, metadata: str) -> None:
    path = tmp_path / "bad-meta.md"
    path.write_text(
        f"---\nname: bad-meta\ndescription: bad\n{metadata}\n---\nbody",
        encoding="utf-8",
    )

    with pytest.raises(SkillParseError):
        parse_skill_file(path, SkillSource.PROJECT)


def test_substitute_arguments_replaces_all_occurrences() -> None:
    assert substitute_arguments("$ARGUMENTS + $ARGUMENTS", "目标") == "目标 + 目标"
    assert substitute_arguments("没有占位符", "目标") == "没有占位符"
    assert substitute_arguments("$ARGUMENTS", "") == ""


def test_catalog_loads_both_layouts_and_project_overrides_user(tmp_path: Path) -> None:
    project_dir = tmp_path / ".Licode" / "skills"
    user_dir = tmp_path / "home-skills"
    write_skill(user_dir, "same", "用户版本")
    write_skill(user_dir, "user-only", directory=False)
    write_skill(project_dir, "same", "项目版本")
    write_skill(project_dir, "project-only", directory=False)

    catalog = isolated_catalog(tmp_path, user_dir)

    assert catalog.names() == ["project-only", "same", "user-only"]
    assert catalog.get("same") is not None
    assert catalog.get("same").prompt_body == "项目版本"  # type: ignore[union-attr]
    assert catalog.get("project-only").is_directory is False  # type: ignore[union-attr]
    assert catalog.get_source_label("same") == "project"
    assert catalog.get_source_label("user-only") == "user"
    assert catalog.get_source_label("missing") == ""
    assert [item.name for item in catalog.summaries()] == catalog.names()


def test_catalog_skips_bad_skill_and_hot_reload_falls_back(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    project_dir = tmp_path / ".Licode" / "skills"
    good_path = write_skill(project_dir, "hot", "第一版")
    (project_dir / "bad.md").write_text("not frontmatter", encoding="utf-8")

    catalog = isolated_catalog(tmp_path)
    assert catalog.names() == ["hot"]
    assert "Skipping project skill 'bad'" in caplog.text

    good_path.write_text(
        good_path.read_text(encoding="utf-8").replace("第一版", "第二版"),
        encoding="utf-8",
    )
    assert catalog.get("hot").prompt_body == "第二版"  # type: ignore[union-attr]

    good_path.write_text("broken", encoding="utf-8")
    assert catalog.get("hot").prompt_body == "第二版"  # type: ignore[union-attr]
    assert "using cache" in caplog.text


def test_catalog_reload_reports_added_removed_and_validates_tools(tmp_path: Path) -> None:
    project_dir = tmp_path / ".Licode" / "skills"
    first = write_skill(project_dir, "first", allowed_tools=["known", "missing"])
    catalog = isolated_catalog(tmp_path)
    registry = ToolRegistry()
    registry.register(DummyTool("known"))

    issues = catalog.validate_tools(registry)
    assert [(item.skill_name, item.tool_name) for item in issues] == [("first", "missing")]

    first.unlink()
    write_skill(project_dir, "second")
    added, removed = catalog.reload()
    assert added == {"second"}
    assert removed == {"first"}
    catalog.remove("second")
    assert catalog.names() == []


def test_catalog_get_and_reload_do_not_restore_a_removed_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skill_path = write_skill(tmp_path / ".Licode" / "skills", "race", "旧版本")
    catalog = isolated_catalog(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    original_parse = parse_skill_file

    def blocking_parse(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        entered.set()
        assert release.wait(timeout=5)
        return original_parse(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("Licode.skills.catalog.parse_skill_file", blocking_parse)
    with ThreadPoolExecutor(max_workers=2) as pool:
        get_future = pool.submit(catalog.get, "race")
        assert entered.wait(timeout=5)
        skill_path.unlink()
        reload_future = pool.submit(catalog.reload)
        release.set()
        assert get_future.result(timeout=5) is not None
        reload_future.result(timeout=5)

    assert catalog.names() == []
    assert catalog.get("race") is None


def test_active_skills_preserve_order_replace_and_clear() -> None:
    active = ActiveSkills()
    active.activate("one", "v1")
    active.activate("two", "v2")
    active.activate("one", "v3")

    assert active.names() == ["one", "two"]
    assert [(item.name, item.body) for item in active.snapshot()] == [
        ("one", "v3"),
        ("two", "v2"),
    ]
    active.clear()
    assert active.snapshot() == []


def test_active_skills_support_concurrent_activation_and_snapshots() -> None:
    active = ActiveSkills()

    def activate(index: int) -> None:
        active.activate(f"skill-{index % 8}", f"body-{index}")
        active.snapshot()

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(activate, range(80)))

    assert set(active.names()) == {f"skill-{index}" for index in range(8)}
    assert len(active.snapshot()) == 8


def test_render_body_and_prompt_blocks(tmp_path: Path) -> None:
    path = write_skill(
        tmp_path,
        "render",
        "处理 $ARGUMENTS",
        allowed_tools=["read_file", "grep"],
    )
    skill = parse_skill_file(path, SkillSource.PROJECT)

    rendered = render_body(skill, "src")
    assert rendered.startswith("This skill is designed to use only these tools")
    assert rendered.endswith("处理 src")
    assert render_skills_catalog([]) == ""
    catalog_block = render_skills_catalog([SkillCatalogItem("render", "测试")])
    assert "## Available Skills" in catalog_block
    assert "- render: 测试" in catalog_block
    assert "LoadSkill" in catalog_block
    assert render_active_skills_block([]) == ""
    active_block = render_active_skills_block([ActiveSkillEntry("render", rendered)])
    assert "## Active Skills" in active_block
    assert "### Skill: render" in active_block


def test_render_body_appends_arguments_when_no_placeholder(tmp_path: Path) -> None:
    skill = parse_skill_file(
        write_skill(tmp_path, "append", "固定 SOP"),
        SkillSource.PROJECT,
    )
    assert render_body(skill, "额外请求").endswith("## User Request\n\n额外请求")
    assert render_body(skill, "") == "固定 SOP"


def test_filter_tool_registry_applies_allowlist_and_keeps_system_tools() -> None:
    registry = ToolRegistry()
    registry.register(DummyTool("one"))
    registry.register(DummyTool("two"))
    registry.register(SystemTool("LoadSkill"))

    assert filter_tool_registry(registry, []) is registry
    filtered = filter_tool_registry(registry, ["two"])
    assert filtered is not registry
    assert [name for name, _ in filtered.items()] == ["two", "LoadSkill"]
    assert [item.name for item in registry.definitions_filtered(["one"])] == [
        "one",
        "LoadSkill",
    ]
    with pytest.raises(SkillDependencyError, match="missing"):
        filter_tool_registry(registry, ["missing"])


@pytest.mark.asyncio
async def test_load_skill_tool_activates_latest_body_and_reports_unknown(tmp_path: Path) -> None:
    skill_path = write_skill(
        tmp_path / ".Licode" / "skills",
        "load-me",
        "第一版",
        allowed_tools=["read_file"],
    )
    catalog = isolated_catalog(tmp_path)
    active = ActiveSkills()
    tool = LoadSkillTool(catalog, active)
    skill_path.write_text(
        skill_path.read_text(encoding="utf-8").replace("第一版", "热更新版"),
        encoding="utf-8",
    )

    result = await tool.execute(json.dumps({"name": "load-me"}))
    unknown = await tool.execute(json.dumps({"name": "missing"}))

    assert not result.is_error
    assert result.content == "Skill load-me activated. SOP pinned to env context."
    assert active.snapshot()[0].body.endswith("热更新版")
    assert "only these tools: read_file" in active.snapshot()[0].body
    assert unknown.is_error and "available: load-me" in unknown.content
    assert tool.read_only and tool.is_system and tool.is_system_tool


@pytest.mark.asyncio
async def test_load_skill_runs_without_approval_and_pins_next_iteration(tmp_path: Path) -> None:
    write_skill(tmp_path / ".Licode" / "skills", "auto", "自动激活 SOP")
    catalog = isolated_catalog(tmp_path)
    active = ActiveSkills()
    registry = ToolRegistry()
    registry.register(LoadSkillTool(catalog, active))
    provider = FakeProvider(
        [
            [
                StreamEvent(tool_calls=[ToolCall("load", "LoadSkill", '{"name":"auto"}')]),
                StreamEvent(done=True),
            ],
            [StreamEvent(text="已执行"), StreamEvent(done=True)],
        ]
    )
    conversation = Conversation()
    conversation.add_user("请使用 auto Skill")
    agent = Agent(
        provider,
        registry,
        "test",
        permission_engine(tmp_path),
    ).with_catalog(catalog)

    outputs = [output async for output in agent.run(conversation, Mode.DEFAULT, asyncio.Event())]

    assert not any(isinstance(output, ApprovalRequest) for output in outputs)
    assert "## Available Skills" in provider.requests[0].system.stable
    assert "## Active Skills" in provider.requests[1].system.environment
    assert "自动激活 SOP" in provider.requests[1].system.environment


@pytest.mark.asyncio
async def test_skill_commands_inline_and_conflict_handling(tmp_path: Path) -> None:
    custom_path = write_skill(tmp_path / ".Licode" / "skills", "custom", "自定义 SOP")
    write_skill(tmp_path / ".Licode" / "skills", "review", "冲突 SOP")
    catalog = isolated_catalog(tmp_path)
    active = ActiveSkills()
    executor = Executor(
        catalog,
        active,
        ToolRegistry(),
        permission_engine(tmp_path),
        "test",
        [provider_config()],
    )
    commands = CommandRegistry()
    register_builtins(commands)
    register_skills_as_commands(commands, catalog, executor)

    custom = commands.lookup("custom")
    review = commands.lookup("review")
    assert custom is not None and custom.description.endswith("[skill]")
    assert review is not None and not review.description.endswith("[skill]")

    custom_path.write_text(
        custom_path.read_text(encoding="utf-8").replace("自定义 SOP", "热更新 SOP"),
        encoding="utf-8",
    )
    ui = RecordingUI()
    await custom.handler(ui)
    assert active.names() == ["custom"]
    assert active.snapshot()[0].body == "热更新 SOP"
    assert ui.injections == [("/custom", "请按照已激活的 custom Skill 执行。")]

    remove_skill_commands(commands)
    assert commands.lookup("custom") is None
    assert commands.lookup("review") is review


@pytest.mark.asyncio
async def test_skill_command_lists_source_mode_and_active_items() -> None:
    ui = RecordingUI()
    ui.catalog_skills = [SkillSummary("review-code", "检查代码", "project", "fork")]
    ui.active_skill_names = ["review-code"]

    await handle_skill(ui)

    assert ui.printed == ["review-code  检查代码  [project/fork]\n\nActive: review-code"]


@pytest.mark.asyncio
async def test_executor_fork_isolates_history_and_filters_tools(tmp_path: Path) -> None:
    write_skill(
        tmp_path / ".Licode" / "skills",
        "forked",
        "独立检查",
        mode="fork",
        context="none",
        allowed_tools=["read_file"],
    )
    catalog = isolated_catalog(tmp_path)
    active = ActiveSkills()
    registry = new_default_registry()
    registry.register(LoadSkillTool(catalog, active))
    provider = FakeProvider([[StreamEvent(text="子任务结果"), StreamEvent(done=True)]])
    conversation = Conversation()
    conversation.add_user("主会话问题")
    executor = Executor(
        catalog,
        active,
        registry,
        permission_engine(tmp_path),
        "test",
        [provider_config()],
        instruction_text="项目指令",
        memory_text="项目记忆",
    )
    executor.bind(provider, conversation)
    skill = catalog.get("forked")
    assert skill is not None

    result = await executor.execute_fork(skill, "")

    assert result == "子任务结果"
    assert conversation.length() == 1
    fork_prompt = provider.requests[0].messages[0].content
    assert fork_prompt.endswith("独立检查")
    assert "only these tools: read_file" in fork_prompt
    assert [tool.name for tool in provider.requests[0].tools or []] == [
        "read_file",
        "LoadSkill",
    ]
    assert "项目指令" in provider.requests[0].system.stable
    assert "项目记忆" in provider.requests[0].system.stable
    assert "## Available Skills" in provider.requests[0].system.stable


@pytest.mark.asyncio
async def test_executor_fork_uses_and_cleans_temporary_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_skill(
        tmp_path / ".Licode" / "skills",
        "temporary",
        "临时执行",
        mode="fork",
    )
    catalog = isolated_catalog(tmp_path)
    executor = Executor(
        catalog,
        ActiveSkills(),
        ToolRegistry(),
        permission_engine(tmp_path),
        "test",
        [provider_config()],
    )
    executor.bind(FakeProvider([]), Conversation())
    observed: list[Path] = []

    async def fake_launch(options: object) -> str:
        runtime = options.runtime  # type: ignore[attr-defined]
        session_dir = Path(runtime.session.session_dir)
        observed.append(session_dir)
        assert session_dir.is_dir()
        assert Path(runtime.session.spill_dir).is_dir()
        assert runtime.context_window == 128000
        return "临时结果"

    monkeypatch.setattr("Licode.agent.launch.launch_fork", fake_launch)
    skill = catalog.get("temporary")
    assert skill is not None

    assert await executor.execute_fork(skill, "") == "临时结果"
    assert len(observed) == 1
    assert not observed[0].exists()


def test_executor_builds_none_recent_and_full_fork_contexts(tmp_path: Path) -> None:
    project = tmp_path / ".Licode" / "skills"
    for context in ("none", "recent", "full"):
        write_skill(project, context, mode="fork", context=context)
    catalog = isolated_catalog(tmp_path)
    executor = Executor(
        catalog,
        ActiveSkills(),
        ToolRegistry(),
        permission_engine(tmp_path),
        "test",
        [provider_config()],
    )
    conversation = Conversation()
    for index in range(4):
        conversation.add_user(f"u{index}")
        conversation.add_assistant(f"a{index}")
    executor.bind(FakeProvider([]), conversation)

    none_skill = catalog.get("none")
    recent_skill = catalog.get("recent")
    full_skill = catalog.get("full")
    assert none_skill is not None and recent_skill is not None and full_skill is not None
    assert executor._build_fork_conversation(none_skill).length() == 0
    assert [
        item.content for item in executor._build_fork_conversation(recent_skill).messages()
    ] == [
        "a1",
        "u2",
        "a2",
        "u3",
        "a3",
    ]
    full = executor._build_fork_conversation(full_skill).messages()
    assert len(full) == 1
    assert full[0].content.startswith("## Previous conversation summary")
    assert "user: u0" in full[0].content and "assistant: a3" in full[0].content


def test_executor_selects_configured_fork_model_and_context_window(tmp_path: Path) -> None:
    write_skill(
        tmp_path / ".Licode" / "skills",
        "modeled",
        mode="fork",
        model="review-provider",
    )
    catalog = isolated_catalog(tmp_path)
    executor = Executor(
        catalog,
        ActiveSkills(),
        ToolRegistry(),
        permission_engine(tmp_path),
        "test",
        [
            provider_config(),
            ProviderConfig(
                name="review-provider",
                protocol="openai",
                api_key="test",
                model="review-model",
                context_window=64000,
            ),
        ],
    )
    skill = catalog.get("modeled")
    assert skill is not None

    provider, context_window = executor._select_provider(skill)

    assert provider.model == "review-model"
    assert context_window == 64000


@pytest.mark.parametrize(
    ("url", "owner", "repo", "ref", "path"),
    [
        (
            "https://github.com/acme/repo/tree/v1/skills/review",
            "acme",
            "repo",
            "v1",
            "skills/review",
        ),
        (
            "https://raw.githubusercontent.com/acme/repo/main/skills/review/SKILL.md",
            "acme",
            "repo",
            "main",
            "skills/review",
        ),
        (
            "https://skills.sh/acme/repo/skills/review",
            "acme",
            "repo",
            "main",
            "skills/review",
        ),
    ],
)
def test_parse_skill_url_formats(url: str, owner: str, repo: str, ref: str, path: str) -> None:
    parsed = parse_skill_url(url)
    assert (parsed.owner, parsed.repo, parsed.ref, parsed.path) == (owner, repo, ref, path)


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/acme/repo/tree/main/skill",
        "https://example.com/acme/repo/skill",
        "https://github.com/acme/repo/blob/main/SKILL.md",
        "https://skills.sh/acme/repo",
    ],
)
def test_parse_skill_url_rejects_invalid_sources(url: str) -> None:
    with pytest.raises(SkillInstallError):
        parse_skill_url(url)


def test_safe_relative_rejects_traversal_and_windows_separators() -> None:
    assert _safe_relative("skills/demo", "skills/demo/references/a.py") == Path("references/a.py")
    with pytest.raises(SkillInstallError):
        _safe_relative("skills/demo", "skills/other/a.py")
    with pytest.raises(SkillInstallError):
        _safe_relative("skills/demo", "skills/demo/../outside.py")
    with pytest.raises(SkillInstallError):
        _safe_relative("skills/demo", "skills/demo/references\\..\\outside.py")


@pytest.mark.asyncio
async def test_download_tree_uses_contents_api_and_writes_files(tmp_path: Path) -> None:
    skill_content = b"---\nname: demo\ndescription: demo\n---\nbody"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(
                200,
                json=[
                    {
                        "type": "file",
                        "path": "skills/demo/SKILL.md",
                        "size": len(skill_content),
                        "download_url": "https://raw.example/SKILL.md",
                    }
                ],
            )
        return httpx.Response(200, content=skill_content)

    source = parse_skill_url("https://github.com/acme/repo/tree/main/skills/demo")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await _download_tree(client, source, tmp_path)

    assert (tmp_path / "SKILL.md").read_bytes() == skill_content


@pytest.mark.asyncio
async def test_download_tree_enforces_declared_file_limit(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            json=[
                {
                    "type": "file",
                    "path": "skills/demo/large.bin",
                    "size": 1024 * 1024 + 1,
                    "download_url": "https://raw.example/large.bin",
                }
            ],
        )

    source = parse_skill_url("https://github.com/acme/repo/tree/main/skills/demo")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SkillInstallError, match="单文件超过"):
            await _download_tree(client, source, tmp_path)


@pytest.mark.asyncio
async def test_download_tree_enforces_actual_file_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("Licode.skills.install.MAX_FILE_SIZE", 1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(
                200,
                json=[
                    {
                        "type": "file",
                        "path": "skills/demo/file.txt",
                        "size": 1,
                        "download_url": "https://raw.example/file.txt",
                    }
                ],
            )
        return httpx.Response(200, content=b"xx")

    source = parse_skill_url("https://github.com/acme/repo/tree/main/skills/demo")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SkillInstallError, match="单文件超过"):
            await _download_tree(client, source, tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("limit_name", "limit_value", "entries", "error"),
    [
        (
            "MAX_FILE_COUNT",
            1,
            [
                {
                    "type": "file",
                    "path": "skills/demo/one.txt",
                    "size": 1,
                    "download_url": "https://raw.example/one.txt",
                },
                {
                    "type": "file",
                    "path": "skills/demo/two.txt",
                    "size": 1,
                    "download_url": "https://raw.example/two.txt",
                },
            ],
            "文件数超过",
        ),
        (
            "MAX_TOTAL_SIZE",
            1,
            [
                {
                    "type": "file",
                    "path": "skills/demo/two-bytes.txt",
                    "size": 2,
                    "download_url": "https://raw.example/two-bytes.txt",
                }
            ],
            "总大小超过",
        ),
    ],
)
async def test_download_tree_enforces_file_count_and_total_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    limit_value: int,
    entries: list[dict[str, object]],
    error: str,
) -> None:
    monkeypatch.setattr(f"Licode.skills.install.{limit_name}", limit_value)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(200, json=entries)
        return httpx.Response(200, content=b"xx")

    source = parse_skill_url("https://github.com/acme/repo/tree/main/skills/demo")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(SkillInstallError, match=error):
            await _download_tree(client, source, tmp_path)


@pytest.mark.asyncio
async def test_download_tree_rejects_deep_or_unsupported_entries(tmp_path: Path) -> None:
    responses = [
        [
            {
                "type": "file",
                "path": "skills/demo/a/b/c/d/e/file.txt",
                "size": 1,
                "download_url": "https://raw.example/file.txt",
            }
        ],
        [
            {
                "type": "symlink",
                "path": "skills/demo/link",
            }
        ],
    ]
    source = parse_skill_url("https://github.com/acme/repo/tree/main/skills/demo")
    for payload in responses:
        transport = httpx.MockTransport(
            lambda request, value=payload: httpx.Response(200, json=value)
        )
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(SkillInstallError):
                await _download_tree(client, source, tmp_path)


@pytest.mark.asyncio
async def test_install_from_url_is_atomic_reloads_and_cleans_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_root = tmp_path / "home" / ".Licode" / "skills"
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    catalog = Catalog(work_dir)
    catalog._user_dir = install_root

    async def fake_download(client: object, source: object, staging: Path) -> None:
        del client, source
        write_skill(staging.parent, "skill", "已安装")

    monkeypatch.setattr("Licode.skills.install._download_tree", fake_download)

    name = await install_from_url(
        "https://skills.sh/acme/repo/demo",
        catalog,
        work_dir,
        install_root=install_root,
    )

    assert name == "skill"
    assert (install_root / "skill" / "SKILL.md").is_file()
    assert catalog.names() == ["skill"]
    assert not list((install_root.parent).glob(".Licode-skill-*"))


@pytest.mark.asyncio
async def test_install_rejects_missing_skill_file_and_cleans_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_root = tmp_path / "home" / "skills"
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    catalog = Catalog(work_dir)
    catalog._user_dir = install_root

    async def fake_download(client: object, source: object, staging: Path) -> None:
        del client, source
        (staging / "README.md").write_text("missing", encoding="utf-8")

    monkeypatch.setattr("Licode.skills.install._download_tree", fake_download)

    with pytest.raises(SkillInstallError, match="不含 SKILL.md"):
        await install_from_url(
            "https://skills.sh/acme/repo/demo",
            catalog,
            work_dir,
            install_root=install_root,
        )
    assert not list(install_root.parent.glob(".Licode-skill-*"))


@pytest.mark.asyncio
async def test_install_network_failure_cleans_staging_and_tool_reports_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_root = tmp_path / "home" / "skills"
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    catalog = Catalog(work_dir)
    catalog._user_dir = install_root

    async def fail_download(client: object, source: object, staging: Path) -> None:
        del client, source, staging
        raise SkillInstallError("网络中断")

    monkeypatch.setattr("Licode.skills.install._download_tree", fail_download)
    with pytest.raises(SkillInstallError, match="网络中断"):
        await install_from_url(
            "https://skills.sh/acme/repo/demo",
            catalog,
            work_dir,
            install_root=install_root,
        )
    assert not list(install_root.parent.glob(".Licode-skill-*"))

    async def fail_install(url: str, got_catalog: Catalog, got_work_dir: Path) -> str:
        del url, got_catalog, got_work_dir
        raise SkillInstallError("网络中断")

    monkeypatch.setattr("Licode.tool.install_skill.install_from_url", fail_install)
    result = await InstallSkillTool(catalog, work_dir).execute(
        json.dumps({"url": "https://skills.sh/acme/repo/demo"})
    )
    assert result.is_error
    assert result.content == "Skill 安装失败: 网络中断"


def test_replace_directory_rolls_back_existing_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "demo"
    staging = tmp_path / "staging"
    destination.mkdir()
    staging.mkdir()
    (destination / "version.txt").write_text("old", encoding="utf-8")
    (staging / "version.txt").write_text("new", encoding="utf-8")
    original_replace = Path.replace

    def fail_staging_replace(path: Path, target: Path) -> Path:
        if path == staging:
            raise OSError("replace failed")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_staging_replace)

    with pytest.raises(OSError, match="replace failed"):
        _replace_directory(staging, destination)
    assert (destination / "version.txt").read_text(encoding="utf-8") == "old"


@pytest.mark.asyncio
async def test_install_skill_tool_runs_reload_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog = isolated_catalog(tmp_path)
    tool = InstallSkillTool(catalog, tmp_path)
    calls: list[str] = []

    async def fake_install(url: str, got_catalog: Catalog, work_dir: Path) -> str:
        assert got_catalog is catalog and work_dir == tmp_path
        calls.append(url)
        return "installed"

    async def on_installed() -> None:
        calls.append("reloaded")

    monkeypatch.setattr("Licode.tool.install_skill.install_from_url", fake_install)
    tool.set_on_installed(on_installed)

    result = await tool.execute(json.dumps({"url": "https://skills.sh/acme/repo/demo"}))
    assert not result.is_error
    assert result.content == "Skill installed installed and reloaded."
    assert calls == ["https://skills.sh/acme/repo/demo", "reloaded"]
    assert not tool.read_only and not tool.is_system
