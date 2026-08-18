# 第 12 章：Hook 生命周期挂钩系统 Plan

## 架构概览

实现分为两层：

1. `Licode.permission.matcher` 提供 ExactMatcher、GlobMatcher、RegexMatcher、NotMatcher 和 `compile_matcher`，供权限规则与 Hook 条件共用。
2. `Licode.hook` 提供事件、规则、字段匹配、YAML Loader、动作 Executor 和有序 Engine；Agent/TUI 只通过 `dispatch` 接入。

模块依赖保持单向：`hook -> permission.matcher`，permission 不依赖 hook；Agent/TUI 持有 HookEngine，command 只通过 UI Protocol 查询规则。

## 组件划分

- `permission/matcher.py`：四种不可变 Matcher、旧 glob 实现与单字符前缀工厂。
- `permission/rule.py`：Rule 持有 `matcher` 与原始 raw；RuleSet 维持 deny 优先和三层权限语义。
- `hook/event.py`：11 个 Event、BLOCKING_EVENTS、解析函数。
- `hook/rule.py`：Condition、AtomCondition、四类动作和 Rule 数据类。
- `hook/matcher.py`：payload 点路径取值、all_of/any_of 求值。
- `hook/loader.py`：双层扫描、YAML 解析、集中校验、Matcher 编译、同名去重。
- `hook/executor.py`：shell/prompt/http/subagent 执行与稳定 JSON。
- `hook/engine.py`：有序分派、only_once、后台任务、失败降级与拦截结果。
- `agent/runtime.py`：pending_reminders、hook_engine、会话重置。
- `agent/__init__.py`：轮次、工具、压缩、停止、通知六类 Agent 事件接线。
- `tui/app.py`、`tui/resume.py`：会话事件与用户提交拦截。
- `command/builtin_hooks.py`：`/hooks` 格式化输出。
- `cli.py`：加载、注入、SessionEnd 兜底和 Engine 关闭。

## 核心接口与数据结构

```python
class Matcher(Protocol):
    def match(self, value: str) -> bool: ...

def compile_matcher(pattern: str, *, is_command: bool) -> Matcher: ...
```

```python
class Event(StrEnum):
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    SESSION_RESUME = "SessionResume"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    STOP = "Stop"
    PRE_USER_MESSAGE = "PreUserMessage"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    PRE_COMPACT = "PreCompact"
    POST_COMPACT = "PostCompact"
    NOTIFICATION = "Notification"
```

```python
@dataclass(frozen=True)
class Rule:
    name: str
    event: Event
    action: Action
    condition: Condition | None = None
    only_once: bool = False
    asyncio_mode: bool = False
    timeout_s: float = 30.0
    source: str = ""
```

```python
@dataclass
class DispatchResult:
    blocked: bool = False
    reason: str = ""
    blocking_hook_name: str = ""
    injected_prompts: list[str] = field(default_factory=list)

class Engine:
    async def dispatch(self, event: Event, payload: Payload) -> DispatchResult: ...
    async def reset_for_new_session(self) -> None: ...
    async def close(self) -> None: ...
```

`SessionRuntime` 新增：

```python
pending_reminders: list[str]
hook_engine: HookEngine | None
def append_reminders(prompts: list[str]) -> None: ...
def take_reminders() -> list[str]: ...
async def reset_for_new_session(session: SessionContext) -> None: ...
```

## 模块交互

### 启动

```text
cli._amain
  -> permission.new_engine(root)
  -> hook.load(root)
     -> project .LiCode/hooks.yaml
     -> user ~/.LiCode/hooks.yaml
  -> new_app(..., hook_engine)
  -> on_mount -> SessionStart
```

### 用户消息

```text
TUI.submit(non-slash)
  -> Engine.dispatch(UserPromptSubmit)
  -> blocked: 显示错误，保留输入，不写 Conversation
  -> allowed: reminders 入 Runtime，写入用户历史，启动 Agent
```

### LLM 轮次

```text
PreCompact -> manage_context -> PostCompact
PreUserMessage
plan reminder + Runtime.take_reminders()
provider.stream
```

### 工具调用

```text
PhaseStart
  -> PreToolUse
     -> blocked: 构造 is_error ToolResult
     -> allowed: permission.check -> execute/deny/approval
  -> PostToolUse（所有结果都触发）
PhaseEnd
```

### 会话切换

```text
/clear: SessionEnd -> Runtime.reset -> SessionStart
/resume: 加载成功 -> SessionEnd -> Runtime.reset -> SessionResume
/exit/Ctrl+C: SessionEnd -> exit
cli finally: 幂等 SessionEnd -> Engine.close
```

## 动作实现

- shell：`asyncio.create_subprocess_shell`，stdin 写稳定 JSON；timeout/cancel 时杀进程；返回码 2 只在阻塞事件表达 block。
- prompt：直接返回 `ExecutionResult.prompt`，Engine 按规则顺序收集。
- http：复用 `httpx.AsyncClient`；默认 JSON body；2xx JSON 中 `decision=block` 表达拦截。
- subagent：仅固定 stderr 占位日志。
- async：Engine 创建后台 task；后台错误由包装协程按统一格式写 stderr。

## 技术决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 匹配前缀 | `=`、`~`、`!`、无前缀 glob | 兼容旧配置且直观 |
| Matcher | Protocol + frozen dataclass | 可复用、不可变、易扩展 |
| Hook 包 | 独立 `Licode.hook` | 避免 permission 反向依赖 |
| Payload | `dict[str, Any]` | 事件字段差异大，便于 JSON 与点路径读取 |
| Rule 顺序 | Loader 列表顺序 | 不引入本章边界外 priority |
| 项目/用户冲突 | 项目先加载，同名用户规则跳过 | 确定性且项目优先 |
| Reminder | SessionRuntime 一次性队列 | 不污染持久历史，和 plan reminder 同一请求组装 |
| PreToolUse | 权限检查前 | Hook 安全策略可先于权限引擎拦截 |
| 同步 Hook | 串行 | 保证拦截和日志顺序 |
| HTTP | httpx AsyncClient | 与现有异步栈一致并复用连接 |
| only_once | Engine 内存集合，由 Runtime 重置 | 不跨进程，符合本章边界 |
| SessionEnd | TUI + CLI 幂等兜底 | 覆盖命令退出和异常退出 |
| subagent | 占位日志 | 留待后续章节，不提前扩展 |

## 文件组织

```text
src/Licode/
  permission/matcher.py
  permission/rule.py
  permission/settings.py
  hook/__init__.py
  hook/event.py
  hook/rule.py
  hook/matcher.py
  hook/loader.py
  hook/executor.py
  hook/engine.py
  agent/runtime.py
  agent/__init__.py
  command/builtin_hooks.py
  command/builtins.py
  command/ui.py
  tui/app.py
  tui/resume.py
  tui/__init__.py
  cli.py
tests/
  permission/test_matcher.py
  hook/test_loader.py
  hook/test_executor.py
  hook/test_engine.py
  hook/test_agent_integration.py
docs/python/ch12/
  spec.md
  plan.md
  task.md
  checklist.md
```
