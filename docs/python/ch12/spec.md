# 第 12 章：Hook 生命周期挂钩系统 Spec

## 背景

LiCode 已支持权限、Slash 命令与 Skill，但这些扩展点都需要显式触发。本章在 Agent 生命周期的固定时刻自动执行声明式动作，用于格式化、拦截、上下文注入和外部通知。Hook 条件与权限规则共用一套匹配语义。

## 目标

- G1：提供覆盖会话、轮次、消息、工具与系统层的 11 个生命周期事件。
- G2：从 YAML 一次性加载 Hook；错误写入 stderr，跳过错误规则但不阻断启动。
- G3：每条规则由必填 event、可选 if、必填 action 构成。
- G4：权限匹配扩展为 exact、glob、regex、not 四类，并与 Hook 条件共用。
- G5：条件支持嵌套字段访问及 all_of/any_of 二选一组合。
- G6：PreToolUse 与 UserPromptSubmit 支持同步拦截，并把原因反馈给模型或用户。
- G7：支持 shell、prompt、http、subagent 四类动作；subagent 本章只占位。
- G8：支持 only_once、async、timeout；拦截事件禁止 async。
- G9：Hook 失败只写 stderr，不中断 Agent 主流程。

## 功能需求

### 权限匹配语法

- F1：权限规则使用结构化 Matcher；无前缀保持既有 glob 语义。
- F2：权限字符串支持 `=value` 精确、`~regex` 正则、`!inner` 反向、无前缀 glob。
- F3：exact 整串相等；regex 加载期编译；not 可嵌套 exact、regex、glob 或 not。
- F4：权限规则解析失败输出 `rule '<raw>' parse failed: <reason>`，其余规则继续加载。
- F5：既有 `Bash(git *)`、文件 glob、Allow/Deny 优先级与权限配置继续工作。

### Hook 配置

- F6：依次扫描项目级 `<root>/.LiCode/hooks.yaml` 与用户级 `~/.LiCode/hooks.yaml`；不存在时静默跳过。
- F7：两层规则叠加；name 只用于日志与 only_once。同名时保留先加载的项目级规则，后到者警告并跳过。
- F8：顶层为 `hooks:` 数组。规则字段为 name、event、if、action、only_once、async、timeout；timeout 默认 30 秒。

### 生命周期事件

- F9：事件及触发点如下：
  - SessionStart：首次进入会话或 `/clear` 新会话后、首条用户消息前。
  - SessionEnd：退出前、`/clear` 关闭旧会话前、`/resume` 离开旧会话前。
  - SessionResume：历史会话恢复完成后、下一条用户消息前。
  - UserPromptSubmit：非 Slash 用户消息写入历史前，可拦截。
  - Stop：Agent 自然停止后、done 事件前；取消和错误不触发。
  - PreUserMessage：每次 provider 请求前。
  - PreToolUse：每个工具调用权限检查前，可拦截。
  - PostToolUse：工具结果产生后、结束事件前；拒绝和错误结果也触发。
  - PreCompact：auto、emergency、manual 三条压缩路径调用前。
  - PostCompact：压缩返回后。
  - Notification：权限审批显示前或流错误上报前。
- F10：所有 payload 含 event、session_id、cwd、mode；事件扩展字段为：
  - 工具事件：tool_name、tool_input；PostToolUse 另含 tool_result、is_error。
  - 用户消息事件：prompt。
  - Notification：kind=`approval|stream_error`、detail。
  - 压缩事件：trigger=`auto|emergency|manual`；PostCompact 另含 before_tokens、after_tokens。
  - Stop：iter。

### 条件表达式

- F11：if 省略表示无条件；存在时只能包含 all_of 或 any_of 中一个。
- F12：组合值为原子条件数组，每项含 field 与 match。
- F13：field 使用点号读取嵌套 payload；路径不存在按空字符串处理。
- F14：match 支持 exact/glob/regex，以及带 inner 的 not；非法 matcher 跳过整条 Hook。
- F15：Matcher 加载期构造，事件分派时实时求值并复用实例。

### 动作

- F16：action.type 只能是 shell、prompt、http、subagent。
- F17：shell.command 由系统 shell 执行；稳定排序的 payload JSON 从 stdin 输入。
- F18：shell 支持 timeout 与 async；超时记录失败。
- F19：拦截事件中 shell 返回码 2 表示拦截，stderr 优先作为原因；0 放行；其它返回码只记失败并放行。
- F20：prompt.text 进入下一次 LLM 请求 reminder，按规则执行顺序追加在 plan reminder 后。
- F21：Hook reminder 仅消费一次，不写入对话历史，也不参与持久化和历史压缩。
- F22：prompt 动作不表达拦截。
- F23：http 支持 url、method、headers、body；默认 POST，缺省 body 时发送稳定排序的 payload JSON，模板使用 `str.format_map`。
- F24：http 支持 timeout 与 async。
- F25：拦截事件中，2xx JSON 响应 `decision=block` 时拦截并使用 reason；其它响应放行，网络、超时、状态和解析错误只记失败。
- F26：subagent 校验 agent_name 与 prompt；执行只输出 `[hook subagent] not yet implemented, skipped: <agent_name>`。

### 执行控制与接入

- F27：only_once 在同一 SessionRuntime 生命周期内只成功执行一次；`/clear`、`/resume` 重置，不持久化。
- F28：async 使用后台 asyncio task；PreToolUse 与 UserPromptSubmit 配置 async 时加载失败。
- F29：同步和异步失败统一输出 `[hook <name>] <event> failed: <reason>`，不重试。
- F30：Hook 独立包包含规则、Loader、Matcher 包装、Engine 与 Executor；通过参数注入 Agent/TUI。
- F31：Agent 与 TUI 在 11 个事件点调用 Engine.dispatch，收集拦截与 prompt。
- F32：PreToolUse 拦截跳过权限和真实工具，生成 `is_error=True` 的 ToolResult，内容为 `[hook <name>] <reason>`；UserPromptSubmit 拦截不写历史、不发请求并保留输入。
- F33：injected_prompts 在下一次 provider 请求构建 reminder 时按序取出并清空。
- F34：新增本地命令 `/hooks`，按 event 分组显示 name、event、action.type、`[once]`/`[async]` 及来源。
- F35：没有已加载规则时 `/hooks` 输出 `No hooks loaded.`。

## 非功能需求

- N1：所有配置错误都降级为 stderr 警告，不阻断进程。
- N2：同步动作和后台动作均传播 `asyncio.CancelledError`；shell 取消时终止子进程。
- N3：拦截事件的同步 Hook 按声明顺序串行执行，每条独立 timeout。
- N4：Hook reminder 不进入持久会话或历史 token 增长部分。
- N5：only_once 与 ActiveSkills 共享会话生命周期，通过 SessionRuntime 重置。
- N6：payload 使用 `json.dumps(..., sort_keys=True)` 稳定序列化。
- N7：权限规则与 Hook 条件共用 `permission.Matcher`，测试覆盖空串、转义、嵌套 not 和空路径。
- N8：subagent 占位日志格式固定，方便后续章节替换。
- N9：hooks.yaml 不存在静默；YAML 或顶层结构错误警告后继续启动。
- N10：http body 模板只支持基础 `str.format_map`，渲染失败按 Hook 失败处理。

## 边界

- 不真实执行 subagent 动作。
- 不持久化 only_once。
- 不提供 priority/order，按 YAML 声明顺序执行。
- 不热更新 hooks.yaml，修改后需重启。
- 不在 TUI 展示 Hook 触发轨迹，只显示拦截结果并写 stderr 失败日志。
- 不实现 Hook 依赖、互斥、独立日志文件、重试、include 或继承。

## 验收标准

- AC1：`Bash(=git status)` 只命中完整的 `git status`。
- AC2：正则权限规则正确命中；非法正则在 stderr 报错并跳过。
- AC3：`Bash(!~^rm)` 命中非 rm 命令，不命中 rm 命令。
- AC4：PreToolUse shell 返回 2 时 write_file 被拦截，文件不创建，模型收到原因。
- AC5：相同 Hook 返回 0 时工具正常放行。
- AC6：SessionStart prompt 出现在首轮 reminder，模型按注入要求回复。
- AC7：PostToolUse async shell 后台执行，不暂停主对话；失败不打断 Agent。
- AC8：async + PreToolUse 配置被警告并跳过。
- AC9：only_once 首次执行，后续跳过；`/clear` 后可再次执行。
- AC10：UserPromptSubmit 正则命中后消息被拦截、输入保留、模型不收到请求。
- AC11：未知 event 被警告并跳过，其余规则继续加载。
- AC12：项目与用户规则合并，`/hooks` 显示两类来源。
- AC13：Stop HTTP 动作收到包含 `event=Stop` 的 POST。
- AC14：PreToolUse HTTP 返回 block 时工具被拦截。
- AC15：subagent 动作只输出固定占位日志，主流程继续。
- AC16：if 同时含 all_of/any_of 时警告并跳过。
- AC17：PowerShell 端到端组合执行无卡顿、无未捕获异常，`/hooks` 始终可用。
