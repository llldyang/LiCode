# 第 12 章：Hook 生命周期挂钩系统 Task

## 文件清单

- 新建 `src/Licode/permission/matcher.py` 与 `tests/permission/test_matcher.py`。
- 修改 `src/Licode/permission/{rule,settings,persist,__init__}.py` 及既有权限测试。
- 新建 `src/Licode/hook/{__init__,event,rule,matcher,loader,executor,engine}.py`。
- 新建 `tests/hook/{test_loader,test_executor,test_engine,test_agent_integration}.py`。
- 修改 `src/Licode/agent/{runtime,__init__}.py` 与 Agent 测试。
- 新建 `src/Licode/command/builtin_hooks.py`，修改 builtins 与 UI Protocol。
- 修改 `src/Licode/tui/{app,resume,__init__}.py` 与 TUI 测试。
- 修改 `src/Licode/cli.py`。
- 新建 `docs/python/ch12/{spec,plan,task,checklist}.md`。

## 有序任务

### T1 Matcher 接口与四种类型

- [x] 实现 Matcher Protocol、ExactMatcher、GlobMatcher、RegexMatcher、NotMatcher。
- [x] 实现 `compile_matcher` 的 `=`、`~`、`!`、glob 前缀语法。
- 验证：`tests/permission/test_matcher.py`。

### T2 Matcher 边界测试

- [x] 覆盖 exact、regex、not exact、not regex、not glob、路径星号、空串和非法正则。
- 验证：Matcher 表驱动测试通过。

### T3 Permission Rule 升级

- [x] Rule 使用 matcher 与 raw，parse_rule 返回规则或错误。
- [x] RuleSet 通过 Matcher 判定且保留 deny/allow 语义。
- 验证：既有权限规则和新增前缀测试通过。

### T4 Permission 错误日志

- [x] `to_rule_set` 对单条解析失败写 stderr 并跳过。
- 验证：capsys 捕获 `parse failed`。

### T5 Permission 回归

- [x] 更新既有 Rule 构造与持久化逻辑。
- [x] 旧 glob、精确持久规则、三层权限与黑名单测试继续通过。
- 验证：权限测试集通过。

### T6 Hook 基础数据结构

- [x] 声明 11 个 Event、阻塞事件集合、条件、动作、Rule 与 Payload。
- 验证：事件数量和阻塞集合测试。

### T7 Hook 字段条件

- [x] 实现点路径取值、缺失空串、标量字符串化、对象稳定 JSON。
- [x] 实现 all_of/any_of 求值。
- 验证：Loader/Engine 条件测试。

### T8 Hook Loader

- [x] 扫描项目级和用户级 hooks.yaml。
- [x] 校验顶层、name、event、if、matcher、action、bool、timeout、async 冲突。
- [x] 合并规则并处理同名冲突。
- 验证：`tests/hook/test_loader.py`。

### T9 Loader 错误与合并测试

- [x] 覆盖 YAML 错、顶层错、字段错、未知 event/action、混合条件、非法 regex、async 阻塞冲突和同名。
- 验证：错误写 stderr 且有效规则保留。

### T10 Hook Engine

- [x] 实现有序 dispatch、条件过滤、only_once、阻塞短路、prompt 收集。
- [x] 实现后台 task 与统一失败日志。
- 验证：`tests/hook/test_engine.py`。

### T11 Hook Executor

- [x] 实现 shell、prompt、http、subagent 占位。
- [x] 实现稳定 JSON、timeout、取消清理和 HTTP 模板。
- 验证：`tests/hook/test_executor.py`。

### T12 Executor 测试

- [x] 覆盖 shell 0/1/2、stdin JSON、超时、prompt、HTTP block/失败/body、subagent 日志。
- 验证：Executor 专项测试通过。

### T13 Engine 测试

- [x] 覆盖声明顺序、拦截短路、prompt、only_once 重置、async 与失败日志。
- 验证：Engine 专项测试通过。

### T14 SessionRuntime 扩展

- [x] 增加 pending_reminders、hook_engine、append/take。
- [x] 会话重置清空 reminder、Active Skills 和 only_once。
- 验证：`tests/test_agent_runtime.py`。

### T15 Agent Hook 框架

- [x] Agent/new_agent 接受 hook_engine。
- [x] 构造通用 payload，注入结果进入 Runtime。
- [x] plan reminder 在前、Hook reminder 在后并一次消费。
- 验证：Agent reminder 集成测试。

### T16 Agent 事件接入

- [x] 接入 Pre/PostCompact、PreUserMessage、Pre/PostToolUse、Stop、Notification。
- [x] 工具拦截跳过权限与执行，并构造错误 ToolResult。
- [x] 权限拒绝与 Hook 拦截仍触发 PostToolUse。
- 验证：Agent Hook 集成测试。

### T17 Agent 接入测试

- [x] 覆盖 tool result 回灌、Phase Start/End、reminder 顺序、Stop、审批/流错误 Notification、manual compact。
- 验证：`tests/hook/test_agent_integration.py`。

### T18 TUI 持有 HookEngine

- [x] App/new_app/CLI 完成 Engine 注入，Runtime 与 Agent 共享实例。
- [x] on_mount 派发 SessionStart。
- 验证：首轮请求包含 SessionStart reminder。

### T19 UserPromptSubmit

- [x] 非 Slash 提交先 dispatch；拦截时保留输入、不写历史、不调用模型。
- 验证：TUI 拦截测试。

### T20 SessionStart/End/Resume

- [x] `/clear`、`/resume`、退出与 CLI 兜底接入事件。
- [x] SessionEnd 幂等，切换会话重置状态。
- 验证：TUI clear/resume/quit 测试。

### T21 `/hooks` 命令

- [x] 注册第 14 条内置命令。
- [x] 按事件分组输出规则、flags 与来源；空规则输出固定文本。
- 验证：命令和 TUI 输出测试。

### T22 CLI Wiring

- [x] 权限引擎后加载 HookEngine，传给 App。
- [x] finally 兜底 SessionEnd、等待后台任务并关闭 HTTP client。
- 验证：CLI 导入与启动测试。

### T23 整体编译与测试

- [x] 全量 pytest、Ruff、Mypy、compileall、diff check 通过。
- 验证：章节最终质量门禁。

### T24 回归修复

- [x] 修复 Matcher 改造涉及的 ch08 测试。
- [x] 将 `/hooks` 引起的 ch10/ch11 命令数量预期更新为 14。
- 验证：全量 pytest 当前通过。

### T25 PowerShell 端到端

- [x] PowerShell 启动 LiCode 并输入真实请求。
- [x] 验证 PreToolUse、SessionStart、PostToolUse async、UserPromptSubmit、Stop HTTP、only_once、错误配置、`/hooks`。
- [x] 对照 checklist 逐项验收并清理临时配置。
- [x] 创建第 12 章独立提交并推送。

## 执行顺序

```text
T1 -> T2 -> T3 -> T4 -> T5
T6 -> T7 -> T8 -> T9
T10 -> T13
T11 -> T12
T14 -> T15 -> T16 -> T17
T18 -> T19 -> T20 -> T21 -> T22
T23 -> T24 -> T25
```
