# 第 15 章：Agent Team 协作 Task

## 文件清单

- 新建 `src/Licode/team/` 的 types、persistence、manager、spawn、backend、mailbox、registry、tasks、tools 与 filelock。
- 新建 `src/Licode/agent/team_hook.py`、`team_mailbox.py` 和 `src/Licode/cli_team_member.py`。
- 新建 `src/Licode/coordinator/__init__.py`。
- 修改 Agent、task Manager、工具过滤、config、permission、command、TUI 与 CLI 接线。
- 新建 `tests/test_team_*.py`、`tests/test_coordinator.py`、`tests/tui/test_team_mail.py` 并扩展既有测试。
- 新建 `docs/python/ch15/{spec,plan,task,checklist}.md`。

## 有序任务

### T1-T4 基础类型、持久化与 Manager

- [x] 实现 Team、TeammateInfo、BackendType 和 Team 异常。
- [x] 实现 sanitize、派生路径、JSON 解析与原子写。
- [x] 实现 Manager 创建、查询、恢复、删除和损坏配置跳过。
- [x] 实现成员 add/set-active/remove，并在修改前重读磁盘成员。
- [x] 覆盖清理名、同名后缀、强制删除、恢复和跨进程写回测试。

### T5-T9 文件锁、邮箱、注册表与共享任务

- [x] 实现 10 次抖动抢锁和 10 秒 stale 回收的公用 filelock。
- [x] 实现 Message/MessageType 与 Box write/read/read_unread/mark_read。
- [x] 实现 AgentNameRegistry 双向覆盖语义。
- [x] 实现共享任务 CRUD、状态过滤、readiness 与双向依赖更新。
- [x] 使用 `tasks.lock` 和原子 `tasks.json`，覆盖并发邮箱及 stale lock 测试。

### T10-T14 三种 Backend

- [x] 定义 Backend Protocol、SpawnRequest 和工厂。
- [x] 按 TMUX、iTerm2、tmux PATH、in-process 的顺序检测。
- [x] 实现 tmux split/new-session、wake 和 kill；detached 命令作为单个 shell command 传入。
- [x] 实现 iTerm2 split/send-text/close-pane。
- [x] 实现 in-process launch/no-op wake/stop。
- [x] 自动化验证命令构造、agent ID 传递、初始任务不进入命令行和失败不静默降级。

### T15-T20 Feature、上下文、过滤与 spawn

- [x] 实现 `fork_teammate` feature 读取。
- [x] 定义 TeamHook、TeamSpawnRequest、TeammateContext 与 IncomingMessage。
- [x] 扩展工具过滤，让 Team 队员获得五个协作工具并阻断不允许的 Team 生命周期能力。
- [x] 实现定义式/Fork spawn、Worktree、session、上下文、系统附录、后端分流和失败回滚。
- [x] 扩展 Agent 工具 team_name 与 plan_mode_required 参数，保留非 Team 原路径。
- [x] 在 Agent 每轮 LLM 前注入未读邮箱，并处理 Plan approve/reject。

### T21-T23 task Manager 与七个工具

- [x] task Manager 接入共享名称注册、完成回调和已停止任务续派。
- [x] 实现 TeamCreate、TeamDelete、TaskCreate、TaskGet、TaskList、TaskUpdate、SendMessage。
- [x] 实现名称、稳定 agent ID 和广播寻址，结构化消息权限与 Pane wake。
- [x] in-process 续派前从 session_dir 恢复 Conversation，再复用 task Manager。
- [x] 验证工具 read_only、参数校验、正常路径、错误路径和上下文可见性。

### T24-T26 Coordinator、配置与 TUI

- [x] 实现 Coordinator 双锁、truthy 解析、allowlist 与四阶段提示词。
- [x] Config 增加 `features.coordinator_mode` 与 `features.fork_teammate`。
- [x] TUI 接收 Team Manager，Coordinator 收窄主 Agent 工具并追加 prompt。
- [x] 状态栏显示 Coordinator 和当前 Team 标签。

### T27 `/team` 命令

- [x] 注册 `/team list/info/delete/kill`。
- [x] 定义 TeamSummary/TeamMemberSummary/TeamAccessor 和 TUI adapter。
- [x] kill 先终止并清理 session/Worktree，再移出花名册。

### T28-T29 CLI 与 Pane 自治循环

- [x] CLI 组装 registry、task Manager、Team Manager、七个工具、AgentTool 和 TUI。
- [x] 增加隐藏的 team-member CLI 参数，先切换 Worktree cwd，再构造依赖。
- [x] 实现无 TUI 邮箱轮询、stdin Wake、Agent 事件输出、Plan/Shutdown 分流与 idle 通知。

### T30-T30b 空闲通知与 Lead 自动唤醒

- [x] task 完成回调更新成员状态并写 Lead 邮箱。
- [x] TUI 每秒轮询 Lead 邮箱，注入 `<team-update>` 并设置事件。
- [x] Lead idle 时自动合成可见消息开轮，busy 时留待下一迭代。
- [x] 轮询与删除共用 Manager 锁，避免清理竞态。

### T31-T32 续派与 Plan 审批

- [x] Pane 消息写入后 wake；in-process 空闲成员恢复 session 并重新运行。
- [x] approve 切换到 default；reject 保持 plan 并注入 feedback。
- [x] 自动化覆盖 in-process 完成、idle 通知、磁盘恢复和续派。

### T33 自动化测试

- [x] Team、backend、mailbox、tasks、tools、spawn、Coordinator、TUI 和过滤定向测试通过。
- [x] 全量 pytest、ruff、format、mypy、compileall 与 diff-check 在最终清理后通过。

### T34 tmux 真实端到端

- [x] tmux 命令构造、Pane 身份参数、wake、kill、错误不降级有自动化测试。
- [ ] 当前 Windows 主机无原生 tmux；WSL 只有 Python 3.10 且无 uv，不能忠实运行要求的 Python 3.12 LiCode tmux E2E。

### T35 in-process 真实端到端

- [x] PowerShell 启动 LiCode TUI，真实触发 TeamCreate、Agent、write_file 和 SendMessage。
- [x] 验证 Worktree 隔离、idle 通知、Lead 自动唤醒、session 续派和强制删除清理。
- [x] PowerShell 双锁启动 Coordinator，验证状态标签、工具白名单和 bash 执行。
