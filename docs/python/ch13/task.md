# 第 13 章：SubAgent 机制与后台任务系统 Task

## 文件清单

- 新建 `src/Licode/subagent`、三个内置角色与对应测试。
- 新建 `src/Licode/tool/filter.py` 与过滤测试。
- 扩展 `src/Licode/agent/__init__.py`，新建 fork、context、run_to_completion、permission_upgrade、agent_tool、launch。
- 新建 `src/Licode/task` 与 Manager/工具测试。
- 新建 `src/Licode/tui/tasks.py`，修改 TUI、CLI、Config 和 Skill Executor。
- 新建 `docs/python/ch13/{spec,plan,task,checklist}.md`。

## 有序任务

### T1-T3 Definition 与解析

- [x] 实现 Source、Definition、名称和必填字段校验。
- [x] 解析 model、maxTurns、permissionMode、dontAsk、background 和正文。
- [x] 覆盖 BOM、非法字段降级、缺失和未闭合 frontmatter 测试。

### T4-T7 内置角色与 Catalog

- [x] 增加 general-purpose、Explore、Plan。
- [x] 使用 importlib.resources 读取并排序。
- [x] 按 builtin、user、project 加载并覆盖；错误文件跳过。
- [x] 实现 resolve/list/list_by_source/fork_definition。

### T8-T9 工具过滤

- [x] 声明三组常量和 FilterParams。
- [x] 按全局、来源、后台、黑名单、白名单过滤。
- [x] 后台保留 `mcp__` 工具，排除 Agent 和任务元工具。

### T10-T16 Agent 扩展

- [x] 增加 system_prompt、max_turns、permission_mode、dont_ask、approval_upgrader、allowed_tools。
- [x] 实现 ContextVar 调用上下文。
- [x] 实现 Fork 克隆、悬空工具结果和标记检测。
- [x] 实现 dontAsk 和 approval_upgrader 分支。
- [x] 实现 run_to_completion、事件转发与 MaxTurnsReached。

### T17-T18 Agent 工具

- [x] 实现稳定 Schema、动态角色描述、参数校验和 parent 回填。
- [x] 实现定义式、Fork、显式后台、超时移交和后台开关。
- [x] 实现定义式 schema 过滤、Fork schema 保留及双层嵌套阻断。

### T19-T24 后台任务与工具

- [x] 实现状态、BackgroundTask、PartialState、Usage 和 Manager。
- [x] 实现 launch、adopt_running、stop、send_message、done queue。
- [x] 聚合 Tool/Usage/last_activity，隔离失败与取消。
- [x] 实现 TaskList、TaskGet、TaskStop、SendMessage。

### T25-T27 TUI 接入

- [x] LiCodeApp 持有 task_mgr、subagent_catalog、agent_tool。
- [x] on_mount 启动完成通知与审批消费。
- [x] task-notification 注入 Runtime reminder。
- [x] 保留 foreground_sub_agent 字段。
- [x] 按最终修订跳过 ESC 手动切后台，只保留显式后台和超时自动转后台。

### T28-T31 Skill、CLI、配置与公共启动

- [x] Skill fork 改为调用 `agent.launch_fork`。
- [x] CLI 注册四个任务工具和 Agent 工具并注入 TUI。
- [x] Config 增加默认开启的 enable_subagent_background。
- [x] 实现 ForkLaunchOpts 与 launch_fork。

### T32-T33 集成与门禁

- [x] 覆盖 Agent 工具完整定义式路径和过滤行为。
- [x] 运行全量 pytest、ruff、format、mypy、compileall、diff-check。
- [x] 完成 PowerShell 真实对话端到端测试。
