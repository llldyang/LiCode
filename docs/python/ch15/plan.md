# 第 15 章：Agent Team 协作 Plan

## 架构概览

本章分为四层：`Licode.team` 管理数据与持久化，`team.backend` 统一三种执行环境，mailbox/registry/tasks 提供协作状态，Agent、CLI、TUI 与 Coordinator 完成运行时接线。

```text
LiCodeApp / Lead
  |-- TeamCreate / TeamDelete -> team.Manager -> config.json
  |-- Agent(team_name) -> TeamHook -> spawn_teammate
  |      |-- worktree.Manager + session.Writer
  |      `-- Backend -> tmux | iterm2 | task.Manager
  |-- Team tools -> tasks.json / mailbox/<agent_id>.json
  `-- lead mailbox watcher -> reminder -> autonomous turn
```

Agent 通过 `TeamHook` 协议调用 Team，避免 Agent 核心反向依赖具体 Manager。in-process Backend 只接收已经构造好的 Agent 与 Conversation，不在 backend 包内组装依赖。

## 组件划分

- `team/types.py`：BackendType、Team、TeammateInfo 和可识别异常。
- `team/persistence.py`：sanitize、路径绑定、JSON 解析与原子替换。
- `team/manager.py`：创建、恢复、删除、成员资源清理、空闲回调和 Lead 邮箱轮询。
- `team/spawn.py`：角色解析、Worktree/session、上下文、后端启动、登记与回滚。
- `team/backend/`：Backend/SpawnRequest、detect、tmux、iTerm2 与 in-process。
- `team/filelock.py`、`mailbox/`：跨进程锁与结构化邮箱。
- `team/registry/`：Agent 名称和 ID 双向注册。
- `team/tasks/`：共享任务 CRUD、过滤、readiness 和双向依赖。
- `team/tools/`：两个生命周期工具和五个协作工具。
- `agent/team_hook.py`、`team_mailbox.py`：无环协议、上下文和每轮消息注入。
- `agent/agent_tool.py`：team_name 分支与队员嵌套启动限制。
- `task/manager.py`：共享名称注册、完成回调与已结束任务续派。
- `coordinator/`：双锁、allowlist 和四阶段提示词。
- `cli_team_member.py`：Pane 后端无 TUI 自治循环。
- `command/builtin_team.py`、`tui/team_adapter.py`：`/team` 命令及适配。
- `tui/tasks.py`、`stream.py`、`app.py`、`view.py`：邮箱 watcher、自动开轮、接线与状态标签。
- `cli.py`、`config.py`：命令行参数、依赖组装和 feature 配置。

## 核心接口与数据结构

```python
@dataclass
class TeammateInfo:
    name: str
    agent_id: str
    agent_type: str = ""
    model: str = ""
    worktree_path: str = ""
    branch: str = ""
    backend_type: BackendType = BackendType.IN_PROCESS
    pane_id: str = ""
    is_active: bool | None = None
    plan_mode_required: bool = False
    session_dir: str = ""

@dataclass
class Team:
    name: str
    sanitized_name: str
    lead_agent_id: str
    backend: BackendType
    members: list[TeammateInfo]
    config_dir: str
    config_path: str
    tasks_path: str
    mailbox_dir: str
```

```python
class Manager:
    async def create(self, name: str, description: str = "") -> Team: ...
    def get(self, name: str) -> Team | None: ...
    def list_(self) -> list[Team]: ...
    async def delete(self, name: str, force: bool = False) -> None: ...
    async def spawn_teammate(self, request: TeamSpawnRequest) -> str: ...
    async def handle_task_done(self, agent_id: str) -> None: ...
    async def poll_lead_mailboxes(self) -> list[LeadMessage]: ...
```

```python
class Backend(Protocol):
    def type(self) -> BackendType: ...
    async def spawn(self, req: SpawnRequest) -> tuple[str, str]: ...
    async def wake(self, pane_id: str, agent_id: str) -> None: ...
    async def kill(self, pane_id: str, agent_id: str) -> None: ...
```

```python
class Box:
    async def write(self, agent_id: str, msg: Message) -> None: ...
    async def read(self, agent_id: str) -> list[Message]: ...
    async def read_unread(self, agent_id: str) -> tuple[list[int], list[Message]]: ...
    async def mark_read(self, agent_id: str, indices: list[int]) -> None: ...

class Store:
    async def create(self, task: Task) -> str: ...
    async def get(self, id_: str) -> Task: ...
    async def list_(self, filter_: Filter | None = None) -> list[Task]: ...
    async def update(self, id_: str, patch: Patch) -> None: ...
```

```python
class AgentNameRegistry:
    def register(self, name: str, agent_id: str) -> None: ...
    def unregister(self, name: str) -> None: ...
    def resolve(self, name_or_id: str) -> str | None: ...
    def name_of(self, agent_id: str) -> str | None: ...
```

## 模块交互

### Team 创建与恢复

```text
TeamCreate -> sanitize -> unique suffix -> detect backend
  -> mkdir team/mailbox -> atomic config -> register lead -> Manager.teams

startup -> scan teams/*/config.json
  -> valid: bind paths + restore registry + probe activity
  -> invalid: stderr warning + skip
```

### 队员启动

```text
Agent(team_name)
  -> TeamHook.spawn_teammate
  -> resolve role/fork -> create Worktree -> create session Writer
  -> build Agent + teammate tool filter + dont_ask + team context
  -> Pane: initial task to mailbox -> spawn CLI process
     in-process: task.Manager.launch(Agent, Conversation, cwd)
  -> add member + register name -> return JSON
  -> failure: kill + delete mailbox/session/Worktree
```

### 消息与续派

```text
SendMessage -> resolve in current Team by ID/name/* -> mailbox lock + atomic append
  -> Pane: backend.wake
  -> in-process running: next Agent iteration ingests mailbox
  -> in-process stopped: load session -> replace Conversation -> task.Manager.send_message

Agent iteration -> read_unread -> approval transition -> append reminder -> mark_read
```

### 完成通知与 Lead 唤醒

```text
task.Manager finish -> on_task_done(agent_id)
  -> Team member inactive -> write lead mailbox

TUI ticker -> poll lead mailboxes -> mark read -> pending reminder + event
  -> busy Lead: next iteration consumes
  -> idle Lead: visible [team-update] user message -> autonomous turn
```

### Coordinator 与收敛

```text
config feature && environment truthy
  -> set Lead allowed tools -> append prompt -> status label
  -> Lead delegates -> waits for notifications
  -> Bash git merge branches -> resolve or git merge --abort
```

## 技术决策

- Team 后端在创建时一次确定；失败显式暴露，避免运行时行为漂移。
- 邮箱与任务均使用 JSON 单文件、独占 lock、stale 回收和原子替换，不引入数据库或 socket。
- Team config 的成员修改先重读磁盘，覆盖 Pane 与 Lead 各持一份对象的场景。
- 队员总是 `dont_ask=True`，安全边界由工具过滤、Plan 模式和 Worktree 提供。
- in-process 复用第 13 章 task Manager，Pane 使用 `python -m Licode --team-member` 独立进程。
- Agent 名称注册表由 task 与 Team 共用；Team 内直接 agent ID 寻址优先查花名册，避免同名覆盖影响稳定 ID。
- in-process 续派以 session 文件为事实来源，再复用 task Manager 的恢复运行路径。
- Team 共享任务锁固定为 `tasks.lock`，与设计持久化格式一致。
- Lead 邮箱轮询与 Team 删除共用 Manager 锁，防止删除期间 watcher 重新创建 mailbox。
- Coordinator 使用固定 allowlist 且本次启动不可解锁；收敛继续使用通用 Bash，不增加专用工具。
- Team 工具名称与第 13 章 TaskGet/TaskList/SendMessage 复用时由组合工具保留旧调用路径，纯 Team 写任务工具按上下文过滤。
