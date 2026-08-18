# 第 12 章：Hook 生命周期挂钩系统 Checklist

## 1. 权限匹配器

- [x] Matcher Protocol 与 Exact/Glob/Regex/Not 四种实现可导入。
- [x] `=git status` 只命中完整字符串。
- [x] `~^npm (install|test)$` 正确命中和排除。
- [x] `!~^rm` 与 `!glob` 正确取反。
- [x] 非法 regex、空 matcher 抛出 ValueError。
- [x] 既有权限 glob、优先级、持久化配置继续工作。
- [x] 权限规则解析失败写 stderr 且只跳过该条。

## 2. Hook 包

- [x] `Licode.hook` 可导入，11 个 Event 完整。
- [x] is_blocking 只对 PreToolUse/UserPromptSubmit 返回 True。
- [x] 项目与用户 hooks.yaml 叠加，项目同名规则优先。
- [x] 文件缺失静默；YAML、顶层、字段、枚举和 matcher 错误均降级。
- [x] all_of/any_of 互斥，嵌套字段缺失按空串。
- [x] async + 阻塞事件在加载期跳过。
- [x] timeout 支持秒、分、时和数值秒。
- [x] Engine 按声明顺序执行，拦截后停止后续同步规则。
- [x] only_once 第二次跳过，会话重置后重新可执行。
- [x] async 后台失败使用固定 stderr 格式。

## 3. 动作执行

- [x] shell 返回 2 在阻塞事件产生 block，stderr 为原因。
- [x] shell 返回 0 放行，其它非零只记失败。
- [x] shell stdin payload JSON key 稳定排序。
- [x] shell timeout 终止进程；取消传播 CancelledError。
- [x] prompt 返回 injected prompt。
- [x] HTTP 默认 POST 与稳定 JSON body。
- [x] HTTP 模板、method、headers 可配置。
- [x] HTTP `decision=block` 在阻塞事件生效。
- [x] HTTP 网络、状态、超时、解析和模板错误不阻断 Agent。
- [x] subagent 只输出固定占位日志。

## 4. Agent 与 TUI 集成

- [x] SessionStart 在首条消息前触发。
- [x] SessionEnd 在 clear、resume、quit 和 CLI finally 路径触发。
- [x] SessionResume 在历史恢复后触发。
- [x] UserPromptSubmit 拦截保留输入、不写历史、不请求模型。
- [x] PreUserMessage 在每次 provider 请求前触发。
- [x] PreToolUse 在权限检查前触发。
- [x] PostToolUse 对成功、错误、权限拒绝和 Hook 拦截结果触发。
- [x] Pre/PostCompact 覆盖 auto、emergency、manual 接线路径。
- [x] Notification 覆盖 approval 与 stream_error。
- [x] Stop 在自然完成的 done 前触发，取消/错误不触发。
- [x] PreToolUse block 回灌 `is_error=True` ToolResult，内容含 Hook 名和原因。
- [x] plan reminder 在前，Hook reminder 按序在后且只消费一次。
- [x] Runtime 新会话清空 reminder、Active Skills 与 only_once。
- [x] `/hooks` 已注册、按事件分组显示 flags 与来源。
- [x] 无 Hook 时 `/hooks` 输出 `No hooks loaded.`。

## 5. 自动化门禁

- [x] `uv run pytest -q` 通过。
- [x] `uv run ruff check src/Licode tests` 通过。
- [x] `uv run ruff format --check src/Licode tests` 通过。
- [x] `uv run mypy src/Licode` 通过。
- [x] `uv run python -m compileall -q src/Licode tests` 通过。
- [x] `git diff --check` 通过。

## 6. PowerShell 端到端

### 场景 1：PreToolUse shell 拦截

- [x] PowerShell 启动 LiCode。
- [x] 真实请求触发 write_file。
- [x] Hook 返回 2 后工具结果显示 `[hook block-write] ...`。
- [x] 目标文件没有创建，模型收到结果后调整答复。

### 场景 2：SessionStart prompt

- [x] 重启后首条英文请求得到中文回复。
- [x] 服务端请求记录的 reminder 含 SessionStart 注入文本。

### 场景 3：PostToolUse async shell

- [x] 工具执行后后台动作运行。
- [x] 主对话不等待后台动作即可进入下一轮。
- [x] 后台失败只写 stderr，不中断 Agent。

### 场景 4：UserPromptSubmit 拦截

- [x] 输入含 delete 的请求被拦截并显示 Hook 原因。
- [x] 输入内容保留，Conversation 与模型请求数不增加。

### 场景 5：Stop HTTP

- [x] Agent 自然完成后本地服务收到一次 POST。
- [x] body 含 `"event":"Stop"`。

### 场景 6：only_once

- [x] 第一轮触发，第二轮不再触发。
- [x] `/clear` 后再次触发。

### 场景 7：错误配置

- [x] async + PreToolUse 在 stderr 报错并跳过。
- [x] LiCode 仍进入 idle，合法 Hook 正常加载。

### 场景 8：`/hooks`

- [x] 输出按 event 分组并显示 action 与 flags。
- [x] 末尾显示加载来源文件。

### 场景 9：组合

- [x] PreToolUse、SessionStart、PostToolUse、UserPromptSubmit 可组合运行。
- [x] 全程不卡顿、无未捕获异常栈。

## 7. Git

- [x] 第 12 章使用独立 commit。
- [x] commit 推送到 `origin/master`。
- [x] 远端完整哈希与本地 HEAD 一致。
