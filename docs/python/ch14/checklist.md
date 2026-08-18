# 第 14 章：Git Worktree 隔离 Checklist

## 1. Worktree 子包

- [x] `Licode.worktree` 可导入，公开 Manager、数据类型、slug 和错误类型。
- [x] slug 校验拒绝路径穿越、空段、点段、非法字符和超长值。
- [x] `flat_slug("team/alice") == "team+alice"`。
- [x] WorktreeSession JSON 字段使用小写下划线，原子写且 None 写为 `null`。
- [x] `_run_git` 设置非交互环境变量和 DEVNULL stdin。
- [x] `_has_worktree_changes` 检测未提交修改和新增提交，错误时 fail closed。
- [x] `_resolve_head_sha_from_fs` 可从真实 Worktree 恢复 SHA。
- [x] Manager 校验 Git 根仓库，创建目录，恢复 session 和 active 映射。
- [x] create 支持普通/嵌套 slug、同名保护和无 Git 子进程的快速恢复。
- [x] 本地配置、hooks、软链和 `.worktreeinclude` 四项设置可观察。
- [x] enter 不改变进程 cwd，并持久化完整 session。
- [x] exit/remove 默认保护变更，discard 可删除目录和分支。
- [x] auto_cleanup 保留 manual/有变更目录，删除无变更临时目录。
- [x] stale sweep 只识别临时名称并跳过当前、有变更或未推送目录。
- [x] `random_agent_name` 匹配 `agent-a[0-9a-f]{7}`。

## 2. Tool cwd

- [x] `with_cwd`、`cwd_from_ctx`、`resolve_path` 正确设置、嵌套和恢复上下文。
- [x] 绝对路径不变，相对路径和空路径使用 ctx cwd 或进程 cwd。
- [x] read_file、write_file、edit_file 在 ctx cwd 下操作对应文件。
- [x] glob、grep 在 ctx cwd 下搜索对应目录。
- [x] bash 子进程的 cwd 为 ctx cwd。
- [x] 六个核心工具 schema 不增加 cwd 字段。

## 3. SubAgent 与 Agent

- [x] Definition 有默认空值 `isolation` 字段。
- [x] parser 接受 `isolation: worktree`，非法值警告并降级为空。
- [x] Worktree notice 含标签、父目录和隔离工作目录。
- [x] 隔离执行创建临时 Worktree，并在 ctx 中传递其 path。
- [x] 完成、异常和取消路径执行 auto_cleanup；保留时回报 path/branch。
- [x] AgentTool 末尾接受可选 worktree_mgr，未配置时返回工具错误。
- [x] 隔离角色声明 background 时仍强制前台，不进入 Task Manager。

## 4. Command 与 TUI

- [x] WorktreeSummary、WorktreeAccessor 可导入，NopUI 返回 None。
- [x] Command 支持可选 args_handler，旧命令解析和 handler 行为不回归。
- [x] `/worktree` 已注册，create/list/enter/exit/remove 分发正确。
- [x] Manager 不可用、未知子命令和非法参数给出错误。
- [x] WorktreeAdapter 转发 Manager 并更新 active cwd。
- [x] LiCodeApp 持有 worktree_mgr 和 active_cwd，已有 session 可恢复。
- [x] 主 Agent 完整运行事件流使用 active cwd ContextVar。

## 5. CLI 与集成

- [x] CLI 初始化 Manager，失败时 stderr 警告并继续启动。
- [x] CLI 把 Manager 注入 AgentTool 和 LiCodeApp。
- [x] 启动时异步执行一次 24 小时 stale sweep。
- [x] `.gitignore` 忽略 `.Licode/worktrees/` 和 `.Licode/worktree_session.json`。
- [x] 工具列表只新增命令层能力，Agent 工具 schema 不变。
- [x] worktree、agent、command、tui 模块可同时导入且无循环导入。

## 6. 自动化门禁

- [x] `uv run pytest -q`。
- [x] `uv run ruff check src/Licode tests`。
- [x] `uv run ruff format --check src/Licode tests`。
- [x] `uv run mypy src/Licode`。
- [x] `uv run python -m compileall -q src/Licode tests`。
- [x] `git diff --check`。

## 7. PowerShell 端到端

- [x] PowerShell 启动 LiCode 并进入 idle。
- [x] 真实对话触发 `isolation: worktree` SubAgent 和文件工具。
- [x] SubAgent 修改只出现在 Worktree，主工作目录文件不变。
- [x] 有变更的临时 Worktree 被保留并显示 path/branch。
- [x] 无变更的临时 Worktree 自动删除。
- [x] `/worktree create` 和 `/worktree list` 显示手动副本。
- [x] `/worktree enter` 后主 Agent 相对路径工具使用 Worktree cwd。
- [x] `/worktree exit --remove` 拒绝有变更目录，`--discard` 可删除。
- [x] `/worktree create ../etc` 和 `/worktree create ..` 被拒绝。
- [x] E2E 临时配置、角色、文件和 Worktree 已清理。

## 8. Git

- [x] 第 14 章独立 commit。
- [x] commit 推送到 `origin/master`。
- [x] 本地 HEAD 与远端完整哈希一致。
