# 第 14 章：Git Worktree 隔离 Task

## 文件清单

- 新建 `src/Licode/worktree` 子包及 `tests/test_worktree_*.py`。
- 新建 `src/Licode/tool/ctx.py`，修改六个核心工具并增加 cwd 测试。
- 修改 `src/Licode/subagent`，新建 `src/Licode/agent/agent_worktree.py` 并接入 AgentTool。
- 扩展 `src/Licode/command` 的参数命令和 Worktree UI 协议。
- 新建 `src/Licode/tui/worktree_adapter.py`，修改 TUI、CLI 和 `.gitignore`。
- 新建 `docs/python/ch14/{spec,plan,task,checklist}.md`。

## 有序任务

### T1 Slug

- [x] 实现 `validate_slug` 和 `flat_slug`。
- [x] 覆盖合法嵌套名、长度、空段、点段、非法字符和路径穿越测试。

### T2-T4 Session、Git helper 与 Manager

- [x] 实现 WorktreeSession JSON 往返、原子写和 `null` 清理。
- [x] 实现非交互 `_run_git`、fail-closed 变更检测和纯文件系统 HEAD 恢复。
- [x] 实现 Manager 根仓库校验、目录初始化、session 恢复和 active 扫描。

### T5 创建与环境初始化

- [x] 实现真实 `git worktree add -B`、同名并发保护和已有目录快速恢复。
- [x] 实现本地配置复制、hooks 继承、大目录软链和 `.worktreeinclude`。
- [x] 所有 post-creation setup 使用 best effort 警告。

### T6 生命周期

- [x] 实现 enter 与 session 持久化，且不改变进程 cwd。
- [x] 实现 exit/remove、变更保护、显式 discard 和恢复兜底。
- [x] 实现 manual/临时 Worktree 的 auto_cleanup。

### T7 Stale sweep

- [x] 实现临时名称生成和 24 小时过期扫描。
- [x] 跳过手动名称、当前 session、有变更和有未推送提交的目录。

### T8-T9 显式 cwd 与六个工具

- [x] 实现 `with_cwd`、`cwd_from_ctx`、`resolve_path`。
- [x] 修改 read/write/edit/glob/grep/bash 使用显式 cwd。
- [x] 验证工具 schema 不增加 cwd 字段。

### T10-T12 SubAgent 与 AgentTool

- [x] Definition 和 parser 增加 isolation，非法值警告并降级。
- [x] 实现 worktree notice、隔离运行、异常/取消清理和保留信息。
- [x] AgentTool 注入可选 Manager；未配置时报错；隔离模式强制前台。

### T13 命令层

- [x] Command 增加可选 args_handler，并保留旧 parse/handler 兼容性。
- [x] 定义 WorktreeSummary、WorktreeAccessor 和 NopUI 空实现。
- [x] 实现 `/worktree` create/list/enter/exit/remove 并注册。

### T14 TUI

- [x] 实现 WorktreeAdapter 和 active cwd 回调。
- [x] LiCodeApp 接受 Manager，并从已有 session 恢复 active_cwd。
- [x] 每次主 Agent Run 使用 `with_cwd` 包住完整异步事件流。

### T15 CLI 与忽略规则

- [x] CLI 初始化 Manager，失败降级，成功时启动 stale sweep。
- [x] Manager 注入 AgentTool 和 LiCodeApp。
- [x] `.gitignore` 增加 Worktree 目录和 session 文件。

### T16 集成与验收

- [x] 运行全量 pytest、ruff、format、mypy、compileall 和 diff-check。
- [x] 在 PowerShell 启动 LiCode 并完成真实对话与 `/worktree` 端到端场景。
- [x] 对照 checklist 逐项确认并清理 E2E 临时文件。
