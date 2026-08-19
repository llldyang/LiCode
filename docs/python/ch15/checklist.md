# 第 15 章：Agent Team 协作 Checklist

## 1. Team 与持久化

- [x] Manager 可构造并自动创建 `~/.Licode/teams`。
- [x] create 落地 config，名称清理和同名 `-2` 后缀正确。
- [x] BackendType 三个值齐全，config 保存后端、描述、时间和完整成员字段。
- [x] Team 成员修改前重读磁盘 members，跨对象写回不丢成员。
- [x] 启动扫描恢复 Team；损坏 config 写 stderr 并跳过。
- [x] 恢复时 in-process 成员标 idle，Pane 成员执行存活探测。
- [x] 非 force 删除有活跃成员时拒绝；force 按顺序 kill、清 session、清 Worktree、清 Team。
- [x] `/team kill` 清资源后再移出成员，不能终止 Lead。

## 2. Backend 与 Team member

- [x] detect 覆盖 TMUX、iTerm2、PATH tmux 和 in-process 优先级。
- [x] Backend Protocol 与工厂可构造三种后端。
- [x] tmux split/new-session、wake/kill 命令构造正确；detached 模式使用单个 shell command。
- [x] iTerm2 split/send-text/close-pane 命令构造正确。
- [x] in-process 调 task Manager launch/stop，wake 为 no-op。
- [x] Pane 命令包含 agent ID、Team、成员、session、Worktree、角色、模型和 Plan flag。
- [x] initial_prompt 不进入 Pane 命令行；spawn 前写入成员邮箱。
- [x] `--team-member` 分支不构造 TUI，自治循环代码覆盖读取、运行、idle 通知与 Wake。
- [x] 所有 Team 队员为 `dont_ask=True`。
- [x] in-process 队员看不到 Agent；Pane 队员不能使用 team_name 向 Team 加人。
- [x] spawn 失败清理已启动后端、邮箱、session 和 Worktree。

## 3. 共享任务、邮箱与注册表

- [x] Task ID 匹配 `task_[0-9a-f]{6}`。
- [x] TaskCreate/Get/List/Update 的字段、过滤和返回格式正确。
- [x] add/remove blocks 与 blocked_by 双向同步，is_ready 反映 blocker 完成状态。
- [x] 共享任务使用 `tasks.lock` 和原子 `tasks.json`。
- [x] Message JSON 字段往返一致，timestamp 自动补齐，默认 unread。
- [x] 10 个并发 writer 向同一邮箱写入无丢失、无截断。
- [x] 11 秒旧锁可回收；10 次仍失败时抛 TimeoutError。
- [x] AgentNameRegistry 名称与 ID 正反查、覆盖和注销正确。
- [x] SendMessage 支持名称、稳定 agent ID 和广播，广播排除发送者。
- [x] Plan 审批仅 Lead 可发，shutdown response 只能发给 Lead。
- [x] Pane 目标执行 wake；in-process 空闲目标恢复 session 后续派。

## 4. Agent、消息注入与 Plan

- [x] Agent 不带 team_name 保持第 13 章原路径。
- [x] Agent 带 team_name 委托 TeamHook，创建 `team-<team>/<member>` Worktree。
- [x] 定义式从空白会话启动；Fork 路径受 feature flag 控制。
- [x] 队员有独立 runtime、session、cwd、allowed tools 和 Team system prompt。
- [x] `<team-context>` 包含 Team、成员名、最终 agent ID、Worktree 和含自己的成员列表。
- [x] 每轮 LLM 前将未读邮箱注入 `<incoming-messages>` 并标 read。
- [x] Plan approve 将权限切到 default；reject 注入 feedback。
- [x] 自然结束触发回调，config 中成员变 idle，Lead 收到 `<member> idle`。
- [x] in-process 续派从 session_dir 重建历史，状态 active 后再次回到 idle。

## 5. Coordinator、命令与 TUI

- [x] feature 与环境变量四种组合中只有双开时启用 Coordinator。
- [x] Coordinator 工具含 Agent、Team/Task/Message、读类工具和 bash，不含 write_file/edit_file。
- [x] Coordinator prompt 含四阶段、派人后等待、禁止 sleep/TaskList 轮询和 merge abort 约束。
- [x] TUI 状态栏显示 `[COORDINATOR]` 与当前 Team。
- [x] `/team list/info/delete/kill` 注册、参数分发与输出正确。
- [x] Lead watcher 轮询所有 Team，标记邮箱已读并注入 `<team-update>`。
- [x] 更新内容单条最多 8000 字符。
- [x] Lead idle 时自动开轮；运行中更新留到下一次 LLM 调用。
- [x] watcher 与 Team 删除通过 Manager 锁串行，删除时不重建 mailbox。
- [x] 沙箱允许 `/tmp`、`/private/tmp`，拒绝 `/etc/passwd`，并阻断软链接逃逸。

## 6. 自动化门禁

- [x] `uv run pytest -q`：495 passed，1 skipped（Windows 符号链接条件性跳过）。
- [x] `uv run ruff check src/Licode tests`。
- [x] `uv run ruff format --check src/Licode tests`。
- [x] `uv run mypy src/Licode`：157 个源文件无错误。
- [x] `uv run python -m compileall -q src/Licode tests`。
- [x] `git diff --check`。
- [x] `uv run python -m Licode --help`。

## 7. PowerShell 真实 E2E：in-process

- [x] PowerShell 启动临时 OpenAI SSE 服务和 LiCode TUI。
- [x] Lead 调 TeamCreate，后端为 in-process，配置落盘。
- [x] Lead 调 Agent 派出 bob，创建 `.Licode/worktrees/team-ch15-e2e+bob`。
- [x] bob 调 write_file 写入 `step1`，再用 SendMessage 汇报。
- [x] bob 完成后 `is_active=false`，Lead watcher 标记消息 read 并自动触发 `[team-update]`。
- [x] `/team info ch15-e2e` 显示成员、状态和 Worktree。
- [x] Lead 续派 bob，复用同一 agent ID/session，文件新增 `step2`。
- [x] bob 第二轮完成后再次 idle，第二轮汇报被消费。
- [x] `/team delete ch15-e2e --force` 清除 Team、session、Worktree 和分支。

## 8. PowerShell 真实 E2E：Coordinator

- [x] 临时配置打开 `features.coordinator_mode`，环境变量打开第二把锁。
- [x] 状态栏显示 `[COORDINATOR]`。
- [x] 模型实际工具列表含读类、bash 和 Team 工具，不含 write_file/edit_file。
- [x] 模型调用 bash 执行 `git status --short`，经用户确认后成功返回。

## 9. Pane 与 Plan 场景

- [x] tmux/iTerm2 后端命令构造、唤醒、终止和失败不降级由自动化测试覆盖。
- [ ] 真实 tmux Pane 全生命周期：当前 Windows 无原生 tmux；WSL 环境为 Python 3.10 且无 uv，不满足项目 Python 3.12 运行条件。
- [ ] 真实 iTerm2 Pane：当前主机不是 macOS，无法执行。
- [x] Plan approve 权限切换、消息注入和 default 恢复由 Agent 集成测试覆盖。
- [ ] 真实 Pane Plan 审批：依赖可用的 tmux/iTerm2 环境，当前未执行。

## 10. Git

- [x] 第 15 章独立 commit。
- [x] commit 推送到 `origin/master`。
- [x] 本地 HEAD 与远端完整哈希一致。
