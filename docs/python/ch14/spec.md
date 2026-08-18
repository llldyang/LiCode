# 第 14 章：Git Worktree 隔离 Spec

## 背景

第 13 章已经支持前台和后台 SubAgent，但多个 Agent 仍共享同一工作目录，并发写文件时会互相覆盖。本章使用 Git Worktree 为指定 SubAgent 和用户手动任务提供独立目录，并通过显式 cwd 将工具调用隔离到对应副本。

## 目标

- G1：提供 Worktree 创建、快速恢复、进入、退出、删除、自动清理和过期清理的完整生命周期。
- G2：严格校验 slug，阻止路径穿越，并把嵌套 slug 安全映射到仓库内 `.Licode/worktrees`。
- G3：创建后复制本地配置、继承 Git hooks、软链大目录，并按 `.worktreeinclude` 复制被忽略文件。
- G4：使用 ContextVar 传递 cwd，不以进程级 `chdir` 切换正常工具执行目录。
- G5：让六个核心工具在 schema 不变的前提下支持显式 cwd。
- G6：支持角色 frontmatter 的 `isolation: worktree`，自动创建临时副本、注入说明并安全清理。
- G7：提供 `/worktree` 命令和 TUI active cwd，支持手动管理与会话恢复。
- G8：启动时恢复 Worktree session，并保守清理过期的临时副本。

## 功能需求

### Slug 与数据结构

- F1：slug 非空、总长不超过 64；每个 `/` 分段只允许 `[a-zA-Z0-9._-]`，拒绝 `.`、`..`、空分段和首尾 `/`。
- F2：`flat_slug` 把 `/` 替换为 `+`；Worktree 目录为 `.Licode/worktrees/<flat_slug>`，分支为 `worktree-<flat_slug>`。
- F3：`Worktree` 保存 name、绝对 path、branch、based_on、head_commit、created 和 manual。
- F4：`WorktreeSession` 保存 original_cwd、worktree_path/name、原分支和 HEAD、session_id、hook_based。

### Manager 与创建

- F5：`Manager(repo_root)` 只接受 Git 仓库根目录，创建 Worktree 目录，读取 session 并从文件系统恢复 active 映射。
- F6：`create` 在状态锁下防止同名并发；新建时执行 `git worktree add -B`，已有目录时只读取 `.git`、HEAD 和 refs 快速恢复。
- F7：复制 `.Licode/config.yaml` 和 `.Licode/settings.local.yaml`，目标已存在时不覆盖。
- F8：优先继承 `.husky`，否则继承仓库 `core.hooksPath`，并为 Worktree 设置绝对 hooks path。
- F9：为 `node_modules`、`.venv`、`vendor` 创建软链。
- F10：读取 `.worktreeinclude` glob，复制匹配的 ignored 文件。
- F11：F7-F10 均为 best effort，失败只写 stderr，不中断创建。

### 生命周期与持久化

- F12：`enter` 记录并原子持久化 session，不改变进程 cwd。
- F13：`exit` 清空 session；REMOVE 默认检测未提交修改和创建后新增 commit，有变更时拒绝删除，显式 discard 才强制删除。
- F14：`remove` 可删除非当前 Worktree，并使用相同变更保护；当前 Worktree 必须通过 `exit`。
- F15：`auto_cleanup` 永远保留 manual Worktree；临时 Worktree 无变更时删除，有变更时保留并返回 path/branch。
- F16：session 使用小写下划线 JSON，先写 `.tmp` 再 `os.replace`；无 session 时持久化 `null`。
- F17：session 无效或目录消失时只警告并清空，不阻断启动。
- F18：`sweep_stale` 只处理超过 24 小时的 `agent-a[0-9a-f]{7}`，跳过当前 session、有变更或有未推送提交的目录。

### 显式 cwd 与工具

- F19：`with_cwd`、`cwd_from_ctx`、`resolve_path` 使用 ContextVar；相对路径以 ctx cwd 或进程 cwd 为基准，绝对路径保持不变。
- F20：read_file、write_file、edit_file、glob、grep 使用 `resolve_path`；bash 子进程使用解析后的 cwd。
- F21：工具名称、描述和参数 schema 不增加 cwd 字段。

### SubAgent 隔离

- F22：`Definition` 增加 `isolation`；解析器只接受空值和 `worktree`，非法值警告并降级为空。
- F23：隔离执行使用随机 `agent-a<7 hex>` 名称，从 HEAD 创建临时 Worktree，并在任务前注入 `<worktree-context>`。
- F24：SubAgent 运行期间通过 `with_cwd(wt.path)` 注入 cwd；完成、异常或取消时执行 `auto_cleanup`。
- F25：有变更而保留时，把 Worktree path 和 branch 追加到结果。
- F26：`isolation: worktree` 未配置 Manager 时返回工具错误；即使角色声明 background 也强制前台执行。

### 命令、TUI 与 CLI

- F27：`/worktree` 提供 create、list、enter、exit、remove 子命令和 `--remove`、`--discard` 参数。
- F28：命令层通过 `WorktreeAccessor` 轻量协议访问 Manager，不反向依赖 TUI。
- F29：TUI 持有可选 Manager 和 active_cwd；启动时恢复当前 session，每次主 Agent Run 都注入 active cwd。
- F30：CLI 初始化 Manager，失败时警告并降级；成功时异步执行一次 24 小时 stale sweep，并注入 AgentTool 和 TUI。
- F31：`.gitignore` 忽略 `.Licode/worktrees/` 和 `.Licode/worktree_session.json`；Manager 发现缺项时只警告。

## 非功能需求

- N1：Git 子进程禁用终端提示，设置 `GIT_TERMINAL_PROMPT=0`、空 `GIT_ASKPASS` 和 DEVNULL stdin。
- N2：状态变更受 `asyncio.Lock` 保护，耗时 Git 操作不长期占锁。
- N3：变更检测和 stale sweep 失败时 fail closed，优先保留目录。
- N4：除 `Manager.exit` 的恢复兜底外不调用 `os.chdir`。
- N5：中文错误和命令输出；既有第 4-13 章测试不得回归。
- N6：兼容 Windows；软链能力不可用时按 best effort 警告。

## 边界

- 不实现 Worktree 合并策略。
- 不实现跨 Worktree 同步或文件 watcher。
- 不实现多 Agent 编排或 Agent Team。
- 不增加主 Agent 专用 merge 工具。
- 不实现跨 LiCode 进程的 Worktree session 共享。
- 不实现 Git 操作重试和指数退避。

## 验收标准

- AC1：合法/非法 slug、嵌套 slug 映射和路径穿越防护符合 F1-F2。
- AC2：真实临时仓库可创建、恢复、进入、退出、保护性删除和自动清理 Worktree。
- AC3：四项创建后设置均可观察，失败不影响主创建结果。
- AC4：session 原子持久化并可恢复，丢失目录时自动清空。
- AC5：六个工具在显式 cwd 下读写/搜索/执行正确，schema 不变。
- AC6：隔离 SubAgent 创建临时 Worktree，收到 notice 和 cwd，主目录文件不受影响。
- AC7：隔离 SubAgent 无变更时自动删除，有变更时保留并回报位置。
- AC8：`/worktree` 五个子命令可用，变更保护和 discard 行为正确。
- AC9：stale sweep 只清理符合模式且可安全删除的过期临时目录。
- AC10：LiCode 可启动，全量 pytest、ruff、format、mypy、compileall 和 diff-check 通过。
