# 第 13 章：SubAgent 机制与后台任务系统 Checklist

## 1. SubAgent 定义

- [x] `Licode.subagent` 可导入，Definition 字段完整。
- [x] frontmatter、BOM、正文、dontAsk 和 permission mode 解析正确。
- [x] 非法 model/mode 警告并降级，错误文件不阻断 Catalog。
- [x] 三个内置角色可通过 importlib.resources 读取。
- [x] builtin -> user -> project 覆盖顺序正确。
- [x] fork_definition 返回 `is_fork()` 为真的临时定义。

## 2. 工具过滤与 Agent

- [x] 五层工具过滤顺序正确。
- [x] 后台只保留基础/MCP 工具，不含 Agent 和任务元工具。
- [x] 定义式 SubAgent 看不到 Agent；Explore 看不到写工具。
- [x] Fork 保留 Agent schema，但调用入口拒绝嵌套。
- [x] system_prompt、max_turns、permission_mode、dont_ask 生效。
- [x] run_to_completion 返回最终文本、转发事件并在上限抛错。
- [x] dontAsk 放行 Ask，Deny/沙箱/黑名单不被绕过。
- [x] approval_upgrader 把请求交给主 TUI。

## 3. Agent 工具

- [x] Schema 含六个参数且 prompt/description 必填。
- [x] 未知 subagent_type 返回错误。
- [x] 定义式前台返回最终文本。
- [x] `run_in_background=true` 立即返回 async_launched。
- [x] Fork 自动后台并带 fork boilerplate。
- [x] 配置关闭后台时显式后台和 Fork 被拒绝。
- [x] 120 秒超时使用 shield 保留原任务并移交 Manager。

## 4. 后台任务

- [x] launch 完成后为 completed 并产生 done 通知。
- [x] 异常为 failed，取消为 cancelled，主程序不崩溃。
- [x] Tool/Usage/last_activity 聚合正确。
- [x] 同名索引指向最新任务。
- [x] SendMessage 只续派 completed 任务并复用 id/会话。
- [x] TaskList、TaskGet、TaskStop、SendMessage JSON 行为正确。
- [x] `<task-notification>` 注入主 Runtime reminder。

## 5. 集成

- [x] LiCodeApp 持有 task_mgr 与 subagent_catalog。
- [x] CLI 注册 Agent 和四个任务工具。
- [x] Skill fork 复用 launch_fork，既有 Skill 测试不回归。
- [x] HookEngine 在 SubAgent 中继续注入。
- [x] Config 默认启用后台且可显式关闭。
- [x] 本章按 T27 跳过 ESC 手动切后台场景。

## 6. 自动化门禁

- [x] `uv run pytest -q`。
- [x] `uv run ruff check src/Licode tests`。
- [x] `uv run ruff format --check src/Licode tests`。
- [x] `uv run mypy src/Licode`。
- [x] `uv run python -m compileall -q src/Licode tests`。
- [x] `git diff --check`。

## 7. PowerShell 端到端

- [x] PowerShell 启动 LiCode 并进入 idle。
- [x] 真实请求触发 Explore Agent，工具行和最终统计可见。
- [x] 真实请求显式启动后台任务，立即获得 task id。
- [x] TaskList/TaskGet 可观察 running/completed 和结果。
- [x] TaskStop 可使长任务进入 cancelled。
- [x] SendMessage 可续派命名任务并收到第二次通知。
- [x] 自定义 dontAsk 角色执行 Ask 工具不弹审批。
- [x] 普通角色 Ask 在主 TUI 显示来源标识并可继续。
- [x] Fork 嵌套调用被阻断。
- [x] 项目级角色覆盖内置角色。
- [x] 非法角色字段只警告，LiCode 仍可启动和调用。
- [x] E2E 临时配置和角色文件已清理，git status 无额外文件。

## 8. Git

- [x] 第 13 章独立 commit。
- [x] commit 推送到 `origin/master`。
- [x] 本地 HEAD 与远端完整哈希一致。
