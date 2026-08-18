# 第 13 章：SubAgent 机制与后台任务系统 Spec

## 背景

LiCode 已具备主 Agent 循环、权限、Skill 和 Hook。本章增加统一 `Agent` 工具，使主 Agent 能以预定义角色或 Fork 当前上下文的方式委派任务，并提供进程内后台任务管理。

## 目标

- G1：提供 schema 稳定的统一 `Agent` 工具。
- G2：使用 Markdown + YAML frontmatter 定义 SubAgent 角色。
- G3：按内置、用户、项目三层加载角色，项目级优先。
- G4：内置 `general-purpose`、`Explore`、`Plan` 三个角色。
- G5：SubAgent 使用独立 Conversation 和 SessionRuntime，共享 Provider、Registry、PermissionEngine 与 HookEngine。
- G6：提供 `run_to_completion` 非交互循环。
- G7：提供显式后台、前台超时自动转后台、完成通知和任务控制工具。
- G8：定义式 SubAgent 不可嵌套；Fork 保留 Agent schema，但入口按调用上下文和 Boilerplate 双重阻断。

## 功能需求

### Agent 工具

- F1：参数包含 `prompt`、`description`、`subagent_type`、`model`、`run_in_background`、`name`；前两项必填。
- F2：`subagent_type` 非空时从 Catalog 解析；未知类型返回结构化错误。
- F3：`subagent_type` 留空时创建 Fork 定义，继承父消息并强制后台。
- F4：`model` 本章只解析并保留，不切换 Provider。
- F5：定义式前台调用返回最终 assistant 文本；显式后台立即返回 task id。
- F6：前台运行超过 120 秒自动转后台并返回 `timed_out_to_background`。
- F7：`enable_subagent_background=false` 时显式后台和 Fork 均返回错误。

### 角色定义与 Catalog

- F8：角色文件位于内置包、`~/.Licode/agents/*.md`、`<root>/.Licode/agents/*.md`。
- F9：frontmatter 字段为 name、description、tools、disallowedTools、model、maxTurns、permissionMode、background。
- F10：Markdown 正文作为子 Agent system prompt。
- F11：name 必须匹配 `[A-Za-z][A-Za-z0-9_-]{0,31}`，description 必填。
- F12：model 只接受 inherit/haiku/sonnet/opus；非法值警告并降级 inherit。
- F13：permissionMode 支持既有权限模式和 dontAsk；非法值警告并降级 default。
- F14：内置解析失败直接抛出；用户与项目文件错误写 stderr 并跳过。
- F15：同名定义按 builtin -> user -> project 顺序覆盖。

### 运行时和权限

- F16：Agent 支持 system_prompt、max_turns、permission_mode、dont_ask、approval_upgrader、allowed_tools。
- F17：`run_to_completion` 可追加任务、转发 Text/Tool/Usage/Approval 事件并返回最终文本。
- F18：达到 max_turns 抛出 `MaxTurnsReached`；取消原样传播；流错误抛出。
- F19：dontAsk 只把权限引擎的 Ask 转为 Allow，Deny、沙箱和黑名单仍生效。
- F20：非 dontAsk 的 Ask 通过 approval_upgrader 升级到主 TUI。
- F21：SubAgent 不注入 MemoryManager，HookEngine 仍生效。

### Fork 与工具过滤

- F22：Fork 深拷贝父历史，补齐未配对 tool call，并追加 `<fork_boilerplate>` 用户消息。
- F23：Boilerplate 禁止再次 Fork、禁止提问、要求直接执行限定任务并以 `Scope:` 开头报告。
- F24：定义式 SubAgent 的工具列表移除 `Agent`。
- F25：Fork 为保持 schema 稳定保留 `Agent`，调用时按 SubAgent 上下文和 Boilerplate 标记拒绝。
- F26：后台工具限制为基础读写、搜索、bash、Skill 安装/加载和 `mcp__` 工具。
- F27：角色 disallowedTools 排除工具；非空 tools 再作为白名单收窄。

### 后台任务

- F28：Manager 提供 launch、adopt_running、get、list、stop、send_message、subscribe_done。
- F29：任务记录 id、name、状态、结果、错误、时间、usage、tool_count、last_activity 和运行对象。
- F30：状态为 running/completed/failed/cancelled；异常只写入任务状态，不使主程序崩溃。
- F31：同名后启动任务覆盖 name 索引；SendMessage 只续派 completed 任务并复用 id、Agent 和 Conversation。
- F32：TaskList、TaskGet、TaskStop、SendMessage 注册为系统工具；后台 SubAgent 白名单仍排除这些元工具。
- F33：完成队列由 TUI 消费，并把 `<task-notification>` 追加到主 Runtime reminder。

### Skill Fork

- F34：既有 Skill fork 通过 `agent.launch_fork` 和 `run_to_completion` 执行，保持原有返回行为。

## 非功能需求

- N1：主 Agent 工具 schema 不随角色文件变化。
- N2：子 Agent 失败隔离，后台完成队列满时只写 stderr。
- N3：后台任务仅在当前进程内，不跨会话持久化。
- N4：既有权限、Skill、Hook、Compact、Memory 和 TUI 测试不得回归。
- N5：所有定义和任务列表有确定性顺序。

## 边界

- 不实现 Worktree 隔离。
- 不实现多 Agent 团队编排。
- 不实现后台任务持久化。
- 不实现插件加载，Source.PLUGIN 仅占位。
- 不实现 TaskCreate。
- 不汇总 SubAgent token 到主 `/status`。
- 不按 `model` 切换 Provider。
- 本章不实现 ESC 手动切后台；只实现显式 `run_in_background=true` 与前台超时自动切后台。

## 验收标准

- AC1：三层 Catalog、内置角色、字段校验和降级行为正确。
- AC2：定义式 Explore 前台执行并返回最终文本，且看不到 Agent/写工具。
- AC3：Fork 消息前缀与父历史一致，悬空 tool call 被补齐。
- AC4：Fork 保留 Agent schema，但嵌套调用返回明确错误。
- AC5：dontAsk 自动放行 Ask；普通角色把审批升级到主 TUI。
- AC6：显式后台立即返回 task id；超时转后台不取消原协程。
- AC7：任务完成、失败、取消、续派和同名覆盖状态正确。
- AC8：四个任务工具可查询、停止和续派任务。
- AC9：任务完成通知只进入下一轮 reminder。
- AC10：配置关闭后台时 Fork 和显式后台均被拒绝。
- AC11：Skill fork 复用公共启动函数，既有 Skill 行为不变。

> 修订：原 AC11“ESC 切后台”按 task T27 的最终范围取消，本章不验收该场景。
