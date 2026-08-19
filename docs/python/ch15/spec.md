# 第 15 章：Agent Team 协作 Spec

## 背景

第 13 章让主 Agent 可以委派 SubAgent，第 14 章用 Git Worktree 隔离了并发文件修改，但通信仍是以主 Agent 为中心的星型结构。本章把主 Agent 升级为 Team Lead：Team 长期保存成员、共享任务和邮箱，队员拥有独立 Conversation、session 与 Worktree，并可相互通信、暂停和续派。

## 目标

- G1：提供持久化 `Team`、`TeammateInfo` 与 `Manager`，允许单进程管理多个 Team。
- G2：提供 `TeamCreate`、`TeamDelete`，完成后端检测、Lead 注册与资源清理。
- G3：扩展 `Agent` 工具的 `team_name` 分支，完成角色解析、Worktree、session、后端启动与花名册登记。
- G4：用统一 `Backend` 协议支持 tmux、iTerm2 与 in-process，检测后不静默降级。
- G5：提供共享任务、点对点消息、广播、结构化消息和跨进程安全持久化。
- G6：队员停止后标记空闲、通知 Lead，并在新消息到达时恢复已有会话续派。
- G7：支持 Plan 提交与 Lead 审批，批准后切换到 default 权限继续执行。
- G8：提供 Coordinator Mode 双锁，收窄 Lead 工具并注入四阶段协调提示词。
- G9：提供 `/team` 命令、Lead 邮箱轮询和空闲时自动唤醒。
- G10：由 Lead 使用 Bash 完成队员分支合并、冲突处理和失败回滚，不新增 merge 工具。

## 功能需求

### Team 数据与生命周期

- F1：`Team` 保存原始名、清理名、Lead ID、默认后端、描述、创建时间、成员及 config/tasks/mailbox 派生路径。
- F2：`TeammateInfo` 保存名称、agent ID、角色、模型、Worktree 路径与分支、后端、pane ID、活动状态、Plan 要求和 session 目录。
- F3：Manager 以 `~/.Licode/teams/<sanitized_name>/config.json` 持久化 Team，并以清理名索引。
- F4：Manager 构造时创建 teams 目录，扫描可解析配置；损坏配置只写 stderr 并跳过。
- F5：Team 名称只保留 `[A-Za-z0-9._-]`，其他连续字符替换为 `-`，清理后为空则拒绝。
- F6：同名 Team 自动使用 `-2`、`-3` 后缀；创建目录、mailbox 和原子 config 后加入内存索引。
- F7：Lead 固定以 `name="lead"`、`agent_id="lead"`、`is_active=None` 作为首个成员。
- F8：add/set-active/remove 在 asyncio 锁内先重读磁盘 members，再修改并以 `.tmp` + `os.replace` 原子写回。
- F9：非 force 删除在任一成员 `is_active != False` 时拒绝；force 删除依次 kill 非 Lead 成员、清 session、清 Worktree、删 Team 目录和注册信息。
- F10：恢复时 in-process 非 Lead 成员统一标为空闲；Pane 成员探测不到 pane 时标为空闲。

### 后端与队员进程

- F11：`BackendType` 取 `tmux`、`iterm2`、`in-process`，Backend 提供 `spawn/wake/kill`。
- F12：`SpawnRequest` 传递 Team、成员、agent ID、Worktree、session、角色、模型、初始任务、Plan 要求及 in-process 对象。
- F13：检测顺序为 `$TMUX`、iTerm2 且 `it2` 可执行、PATH 中 tmux、in-process；只检测一次。
- F14：tmux 内使用横向 `split-window`，会话外使用 detached `new-session`；失败直接报错，不回退。
- F15：tmux 使用 `send-keys` 唤醒、`kill-pane` 终止；iTerm2 使用 `split/send-text/close-pane`。
- F16：in-process 通过 `task.Manager.launch` 启动，通过 `stop` 终止，wake 为 no-op，cwd 固定到成员 Worktree。
- F17：Pane 命令包含 `--agent-id` 等身份参数，但初始任务不得进入命令行，应预写成员邮箱。
- F18：`--team-member` 不启动 TUI；它构造独立 Agent 后循环读邮箱、运行到完成、打印只读事件流、通知 Lead 并等待唤醒。
- F19：所有 Team 队员强制 `dont_ask=True`；in-process 队员不能继续启动 Agent，Pane 队员只能启动普通 SubAgent，不能向 Team 加人。

### Team spawn

- F20：`TeamCreate(team_name, description?, agent_type?)` 返回清理名、后端和配置路径；agent_type 本章保留不用。
- F21：`TeamDelete(team_name, force?)` 调用 Manager 删除并返回可观察结果。
- F22：`Agent` schema 增加 `team_name` 与 `plan_mode_required`；不带 team_name 时保持第 13 章路径。
- F23：Team spawn 校验 Team 与调用者，按指定角色或受 `fork_teammate` 控制的 Fork 路径解析定义。
- F24：成员 Worktree 名为 `team-<team>/<member>`，映射到 `.Licode/worktrees/team-<team>+<member>`；每名成员有独立 session。
- F25：队员获得协作工具、Team system prompt 附录和 `<team-context>` reminder；返回 member、agent、Worktree、backend 与 pane ID。
- F26：spawn 任一步失败时终止已启动后端并清理邮箱、session 与 Worktree，不保留半成品成员。

### 共享任务

- F27：`TaskCreate` 接受 title、description、assignee、blocked_by，生成 `task_<6 hex>` 并写 `tasks.json`。
- F28：`TaskGet` 返回单个任务；`TaskList` 可按四种状态过滤并返回 `is_ready`。
- F29：`TaskUpdate` 更新文本、状态、负责人及 add/remove blocks/blocked_by，并维护双向关系。
- F30：共享任务使用 `tasks.lock` 跨进程串行 read-modify-write，并以原子替换保存 `tasks.json`。

### 邮箱、寻址与消息

- F31：Message 保存 from、to、type、summary、content、payload、timestamp 与 read。
- F32：消息类型为 text、shutdown_request、shutdown_response、plan_approval_response。
- F33：邮箱路径为 `<team>/mailbox/<agent_id>.json`；Box 提供 write/read/read_unread/mark_read。
- F34：每个邮箱使用同名 `.lock`，以 `O_CREAT|O_EXCL` 抢占；5–100ms 抖动、最多 10 次、超过 10 秒清 stale lock。
- F35：写入自动补时间戳、默认 unread，并通过临时文件和 `os.replace` 原子替换。
- F36：AgentNameRegistry 维护 name 到 ID 与 ID 到 name 的双向映射，后注册同名覆盖旧映射。
- F37：`SendMessage` 支持 Team 内名称、agent ID 和 `*` 广播；广播排除发件人。
- F38：plan_approval_response 仅 Lead 可发；shutdown_response 只能发给 Lead。
- F39：Pane 收件后执行 wake；in-process 空闲成员从 session 恢复 Conversation 后通过 task Manager 续派。

### 消息注入、空闲与审批

- F40：队员每次调用 LLM 前读取未读消息，以 `<incoming-messages>` reminder 注入并标记已读。
- F41：Lead 由 TUI 每秒轮询所有 Lead 邮箱，形成最多 8000 字符内容的 `<team-update>` reminder。
- F42：Lead 正在运行时在下一次 LLM 调用前消费 reminder；Lead 空闲时合成可见的 `[team-update]` 用户消息并自动启动新一轮。
- F43：队员自然完成、失败或取消后触发回调，更新 `is_active=False` 并向 Lead 发送 `<name> idle`。
- F44：in-process 队员续派前设为 active，任务完成后再次回到 idle；Conversation 沿用 session 历史。
- F45：Plan 队员以 plan 权限起步，通过 SendMessage 提交文本计划。
- F46：Lead 发送 plan_approval_response；approve 切到 default，reject 注入 feedback 并继续 plan。

### Coordinator 与收敛

- F47：配置 `features.coordinator_mode` 与环境变量 `LICODE_COORDINATOR_MODE`（兼容设计原名 `MEWCODE_COORDINATOR_MODE`）均为真时启用。
- F48：Coordinator 白名单为 Agent、Team/Task/Message 工具、read_file、glob、grep、bash；不含 write_file/edit_file。
- F49：Coordinator system prompt 使用 Research、Synthesis、Implementation、Verification 四阶段，并要求派人后停止重复探索、等待自然通知。
- F50：Coordinator 一次启动后不能运行时解锁；状态栏显示 `[COORDINATOR]`。
- F51：Lead 使用 Bash 逐个 `git merge worktree-team-<team>+<member> --no-ff`；无法解决时执行 `git merge --abort` 并保留 Worktree 上报。

### 命令与集成

- F52：`/team list` 输出 Team、后端、成员数和活动数。
- F53：`/team info <name>` 输出配置路径及成员 ID、后端、Worktree、pane、活动状态和任务计数。
- F54：`/team delete <name> [--force]` 删除 Team；`/team kill <member>` 终止成员并先清资源再移出花名册。
- F55：TeamCreate/TeamDelete 对 Lead 可见；纯 Team 新增写任务工具不泄漏给普通 Lead，协作工具注入 Team 队员，Coordinator 使用完整协调白名单。
- F56：权限沙箱允许项目根之外的 `/tmp` 与 `/private/tmp`，仍拒绝 `/etc` 等其他路径，并先解析软链接。

## 非功能需求

- N1：Manager 与 Team 内存状态分别使用 asyncio 锁；后端慢操作不持 Team 锁。
- N2：邮箱和共享任务使用同一套跨进程文件锁，写入均为原子替换。
- N3：错误消息、TUI 输出和必要代码注释使用中文；固定协议提示词保留设计原文。
- N4：Coordinator 以不可由模型解除的 allowlist 实现。
- N5：后端选择可预测，spawn 失败不静默改用另一后端。
- N6：第 4–14 章既有测试不得回归，包之间避免循环导入。
- N7：macOS/Linux 提供 Pane 后端；Windows 本章不承诺 iTerm2 特殊适配。

## 边界

- 不做跨进程共享同一活跃 Team，也不做跨机器分布式 Team。
- 不做 socket 实时流式通信，队员通信只使用邮箱文件、轮询和 Wake。
- 不做优先级、deadline、SLA 或自动任务分配。
- 不做队员 token/超时硬限额。
- 不定义结构化 Plan 类型，计划正文仍是普通消息。
- 不提供专用 merge 工具、插件后端、运行时 Coordinator 解锁或跨 Team 寻址。

## 验收标准

- AC1：Team 创建、清理名、同名后缀、恢复、损坏配置跳过和强制删除符合 F1–F10。
- AC2：三种 Backend 的命令、检测优先级、wake/kill 和失败不降级可测试。
- AC3：Team spawn 创建隔离 Worktree/session、注入上下文、登记成员，失败路径清理完整。
- AC4：共享任务 ID、过滤、readiness 与双向依赖正确，使用 `tasks.lock`。
- AC5：邮箱往返、10 路并发写、stale lock、名称/ID/广播寻址及类型权限正确。
- AC6：队员收到消息 reminder，Plan approve 切换权限，完成后 Team 与 Lead 邮箱状态正确。
- AC7：in-process 队员完成后可从 session 恢复历史并续派，cwd 始终位于 Worktree。
- AC8：Lead 邮箱 watcher 能标记消息已读、注入更新，并在 idle 时自动开轮。
- AC9：Coordinator 双锁、工具白名单、提示词和状态栏正确，bash 可用而写文件工具不可见。
- AC10：`/team` 四个子命令和资源清理可观察。
- AC11：`python -m Licode --help`、pytest、ruff、format、mypy、compileall 和 diff-check 全部通过。
- AC12：PowerShell 中完成真实 in-process Team 生命周期与 Coordinator 对话 E2E；tmux/iTerm2 真实 E2E 需在具备对应终端和 Python 3.12 环境的平台执行。
