# 第 13 章：SubAgent 机制与后台任务系统 Plan

## 架构概览

实现分为四层：`Licode.subagent` 负责角色定义和 Catalog；`Licode.agent` 负责 Fork、非交互循环和统一 Agent 工具；`Licode.task` 管理后台生命周期；CLI/TUI 负责注册、父 Agent 回填、审批与完成通知。

```text
cli
  -> load_catalog(root)
  -> task.Manager
  -> Registry + Agent/Task* tools
  -> LiCodeApp
       -> main Agent
       -> AgentTool.set_parent(main Agent)
       -> consume task done / approvals
```

## 组件划分

- `subagent/definition.py`：Source、Definition。
- `subagent/parser.py`：UTF-8、frontmatter、字段校验与降级。
- `subagent/embed.py`：importlib.resources 加载内置 Markdown。
- `subagent/catalog.py`：三层加载、覆盖、查询和 Fork 临时定义。
- `tool/filter.py`：全局、来源、后台、黑名单、白名单五层过滤。
- `agent/fork.py`：Fork Boilerplate、消息克隆和标记检测。
- `agent/context.py`：ContextVar 标记当前调用 Agent 与 Conversation。
- `agent/run_to_completion.py`：消费 Agent 事件并返回最终文本。
- `agent/agent_tool.py`：参数校验、角色选择、工具过滤、前后台启动和防嵌套。
- `agent/launch.py`：Skill fork 复用的公共启动函数。
- `task/manager.py`：后台状态、聚合、完成队列、停止和续派。
- `task/tools.py`：四个任务工具及 JSON 序列化。
- `tui/tasks.py`：任务通知和子 Agent 审批消费。
- `config.py`、`cli.py`、`tui/app.py`：配置与依赖接线。

## 核心接口

```python
@dataclass
class Definition:
    name: str
    description: str
    tools: list[str]
    disallowed_tools: list[str]
    model: Literal["haiku", "sonnet", "opus", "inherit"]
    max_turns: int
    permission_mode: Mode
    dont_ask: bool
    background: bool
    system_prompt: str
    file_path: str
    source: Source
```

```python
class Agent:
    async def run_to_completion(
        self,
        conv: Conversation,
        task: str,
        events: asyncio.Queue | None = None,
    ) -> str: ...
```

```python
class Manager:
    async def launch(self, agent, conv, name, task_text) -> str: ...
    async def adopt_running(self, agent, conv, name, events, handle, partial) -> str: ...
    async def stop(self, task_id: str) -> bool: ...
    async def send_message(self, name: str, message: str) -> str: ...
    def get(self, task_id: str) -> BackgroundTask | None: ...
    def list(self) -> list[BackgroundTask]: ...
    def subscribe_done(self) -> asyncio.Queue[str]: ...
```

## 模块交互

### 定义式前台

```text
main Agent -> AgentTool
  -> Catalog.resolve
  -> apply_agent_tool_filter
  -> child Agent + blank Conversation + independent Runtime
  -> wait_for(shield(run_to_completion), 120s)
  -> final text 或 adopt_running
```

### Fork 后台

```text
main Agent -> AgentTool(subagent_type="")
  -> build_forked_messages(parent messages, prompt)
  -> child Agent（保留 Agent schema）
  -> Manager.launch
  -> {task_id, status: async_launched}
```

### 完成通知

```text
runner -> status/result/error -> done queue
TUI consumer -> build_task_notification
             -> SessionRuntime.append_reminders
下一次 Agent 请求 -> take_reminders
```

### 权限

```text
PermissionEngine.check
  -> Deny: 始终拒绝
  -> Allow: 执行
  -> Ask + dontAsk: 执行
  -> Ask + approval_upgrader: 主 TUI 审批
  -> upgrader 未处理: 原 Agent Approval 事件
```

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 角色格式 | Markdown + YAML | 正文适合系统提示，元数据结构化 |
| 覆盖顺序 | builtin -> user -> project | 项目约束优先 |
| 并发上下文 | ContextVar | 并发工具调用互不污染 |
| 前台超时 | `wait_for(shield(task))` | 超时后原协程继续，可移交后台 |
| 完成通知 | Runtime reminder | 不污染持久历史和用户视图 |
| 工具过滤 | 只过滤子 Agent definitions | 主 Agent schema 稳定 |
| Fork 嵌套 | 调用上下文 + Boilerplate | 保留缓存 schema 并提供兜底 |
| model | 解析保留 | 本章不扩展 Provider 路由 |
| ESC | 不实现 | AgentTool 同步 await 下需额外 TUI 控制协议，按 T27 留后续 |

## 文件组织

```text
src/Licode/
  subagent/{__init__,definition,parser,catalog,embed}.py
  subagent/builtin/{general-purpose,explore,plan}.md
  agent/{__init__,context,fork,run_to_completion,permission_upgrade,agent_tool,launch}.py
  task/{__init__,manager,tools}.py
  tool/filter.py
  tui/tasks.py
tests/
  subagent/
  agent/
  task/
  tool/test_filter.py
  tui/test_consume_task_done.py
docs/python/ch13/{spec,plan,task,checklist}.md
```
