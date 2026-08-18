# 第 14 章：Git Worktree 隔离 Plan

## 架构概览

实现分为四层：`Licode.worktree` 封装 Git Worktree 生命周期；`Licode.tool` 通过 ContextVar 解析显式 cwd；`Licode.subagent` 与 `Licode.agent` 负责隔离角色执行；命令、TUI 和 CLI 负责人工入口、运行上下文及启动恢复。

```text
cli -> worktree.Manager -> AgentTool / LiCodeApp
                            |             |
                            |             -> WorktreeAdapter -> /worktree
                            |             -> with_cwd(active_cwd) -> main Agent
                            -> isolation: worktree
                               -> create -> notice -> with_cwd -> child Agent
                               -> auto_cleanup
```

## 组件划分

- `worktree/slug.py`：slug 校验和扁平化。
- `worktree/session.py`：WorktreeSession 与原子 JSON 持久化。
- `worktree/git.py`：非交互 Git 子进程、变更检测和纯文件系统 HEAD 恢复。
- `worktree/manager.py`：数据结构、构造、session/active 恢复及公开方法。
- `worktree/create.py`：创建、快速恢复和四项 post-creation setup。
- `worktree/lifecycle.py`：enter、exit、remove、auto_cleanup 和保护性错误。
- `worktree/sweep.py`：临时名称生成和过期清理。
- `tool/ctx.py`：显式 cwd ContextVar；六个工具消费该上下文。
- `subagent/definition.py`、`parser.py`：isolation 字段和降级规则。
- `agent/agent_worktree.py`：notice、隔离执行及自动清理。
- `agent/agent_tool.py`：可选 Manager 注入和强制前台分支。
- `command/builtin_worktree.py`：带参数的 `/worktree` 子命令。
- `command/ui.py`：WorktreeSummary 和 WorktreeAccessor。
- `tui/worktree_adapter.py`：Manager 到命令协议的适配和 active cwd 回调。
- `tui/app.py`、`tui/stream.py`：恢复 active cwd，并包住每次主 Agent Run。
- `cli.py`、`.gitignore`：初始化、降级、过期清理和忽略规则。

## 核心接口与数据结构

```python
@dataclass
class Worktree:
    name: str
    path: str
    branch: str
    based_on: str
    head_commit: str
    created: datetime
    manual: bool

@dataclass
class WorktreeSession:
    original_cwd: str
    worktree_path: str
    worktree_name: str
    original_branch: str
    original_head_commit: str
    session_id: str
    hook_based: bool = False
```

```python
class Manager:
    async def create(self, name: str, base_ref: str = "HEAD", manual: bool = False) -> Worktree: ...
    async def enter(self, name: str) -> WorktreeSession: ...
    async def exit(self, name: str, action: ExitAction, opts: ExitOptions) -> ExitReport: ...
    async def remove(self, name: str, opts: ExitOptions) -> None: ...
    async def auto_cleanup(self, name: str) -> AutoCleanupReport: ...
    async def sweep_stale(self, cutoff: datetime) -> list[str]: ...
    def list(self) -> list[Worktree]: ...
    def get(self, name: str) -> Worktree | None: ...
    def current_session(self) -> WorktreeSession | None: ...
```

```python
@contextmanager
def with_cwd(directory: str): ...

def cwd_from_ctx() -> str | None: ...
def resolve_path(path: str) -> str: ...
```

```python
@dataclass
class WorktreeSummary:
    name: str
    path: str
    branch: str
    active: bool
    manual: bool

class WorktreeAccessor(Protocol):
    async def create(self, name: str) -> tuple[str, str]: ...
    def list(self) -> list[WorktreeSummary]: ...
    async def enter(self, name: str) -> None: ...
    async def exit(self, action: str, discard: bool) -> bool: ...
    async def remove(self, name: str, discard: bool) -> None: ...
```

## 模块交互

### 创建与快速恢复

```text
validate_slug -> reserve pending name
  -> path exists: read .git/HEAD/refs only -> active
  -> path absent: git worktree add -B
       -> local config -> hooks -> symlinks -> .worktreeinclude
       -> rev-parse HEAD -> active
```

### 隔离 SubAgent

```text
AgentTool.resolve Definition
  -> isolation == worktree
  -> Manager available, force foreground
  -> create(agent-a<hex>, HEAD, manual=False)
  -> build_worktree_notice
  -> with_cwd(wt.path)
  -> run_to_completion
  -> auto_cleanup
  -> append retained path/branch when changed
```

### 手动 Worktree

```text
/worktree <args>
  -> args_handler
  -> LiCodeApp.worktree_accessor()
  -> WorktreeAdapter
  -> Manager
  -> enter/exit callback updates active_cwd
  -> next main Agent run uses with_cwd(active_cwd)
```

## 技术决策

- 使用 Git 原生 Worktree，不复制完整仓库和版本库。
- Worktree 放在仓库内被忽略目录，便于定位且不被提交。
- ContextVar 隔离并发协程的 cwd；不依赖全局 `chdir`。
- 快速恢复不启动 Git 子进程，降低启动开销。
- 创建后设置使用 best effort，Git Worktree 创建仍是唯一硬失败点。
- 隔离与后台组合本章强制前台，后台 Worktree 生命周期留待后续编排能力。
- 删除和过期清理采用 fail closed，无法确认安全时保留用户数据。
