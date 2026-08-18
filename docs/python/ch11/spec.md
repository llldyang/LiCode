# 第 11 章：Skill 系统 Spec

## 1. 背景

LiCode 用户会反复输入 commit、代码审查、测试执行等操作说明。把这类说明写死在命令中或反复手工输入，会造成复用困难、工具选择噪声增大，并且无法按任务隔离上下文。

Skill 将可复用 SOP 保存为带 YAML frontmatter 的 Markdown 文件。Agent 启动时只读取名字和说明，需要执行时再加载完整正文。

## 2. 目标

- 支持单文件和目录型 Skill。
- 支持项目级、用户级两个来源，项目级同名 Skill 优先。
- 支持 Catalog 摘要注入与完整 SOP 按需激活。
- 支持共享主会话的 inline 模式和隔离子会话的 fork 模式。
- 支持工具白名单、系统工具豁免和依赖校验。
- 支持斜杠短命令、热重载、清空会话时清理激活状态。
- 支持从三类远程 URL 安装目录型 Skill。

## 3. 功能需求

### 3.1 定义与解析

- Skill 使用 `---` 包围的 YAML frontmatter，分隔符后的 Markdown 为 SOP 正文。
- 元数据包含 `name`、`description`、`allowed_tools`、`mode`、`model`、`fork_context`。
- `name` 必须匹配 `^[a-z][a-z0-9-]*$`。
- `mode` 只允许 `inline` 或 `fork`，默认 `inline`。
- `fork_context` 只允许 `none`、`recent` 或 `full`，默认 `none`。
- 单文件布局为 `<skills>/<name>.md`。
- 目录布局为 `<skills>/<name>/SKILL.md`，目录中可带参考资料和脚本。
- `$ARGUMENTS` 在执行前替换为用户参数；当前斜杠命令仍遵循第 10 章零参数约束。

### 3.2 Catalog 与热重载

- 用户目录为 `~/.LiCode/skills`。
- 项目目录为 `<work_dir>/.LiCode/skills`。
- 先扫描用户目录，再扫描项目目录，项目级同名定义覆盖用户级定义。
- 单个 Skill 解析失败只记录 warning，不阻断其他 Skill。
- 启动时缓存解析结果；每次 `get(name)` 都重读源文件。
- 热重载失败时返回最近一次有效缓存并记录 warning。
- Catalog 提供稳定排序的列表、来源标签和工具依赖校验。

### 3.3 渐进式披露与激活态

- 稳定 system prompt 只包含 `name + description` 的 `## Available Skills` 列表。
- 列表提示 Agent 在请求匹配时调用 `LoadSkill`。
- `LoadSkill` 成功后把完整 SOP 放入当前会话的 `ActiveSkills`。
- 每轮 Agent 迭代重建 environment 时追加 `## Active Skills`。
- 多个 Skill 可同时激活；重复激活同名 Skill 时原位置更新为最新正文。
- `/clear` 和新会话重置会清空激活状态。

### 3.4 执行模式

inline 模式：

- 从 Catalog 热重载 Skill。
- 渲染正文和工具提示。
- 激活 SOP 后通过 UI 注入一次用户消息，进入主 Agent 循环。
- 对话结果保留在主历史。

fork 模式：

- 创建独立 `Conversation`、`SessionRuntime` 和临时会话目录。
- `none` 不携带历史。
- `recent` 携带主对话最近 5 条 user/assistant 消息。
- `full` 把主对话拼为一条 `## Previous conversation summary` 消息。
- 可按 `model` 选择已配置 provider；未指定时复用主 provider。
- 子 Agent 完整运行后把累计文本作为 assistant 消息回流 UI。
- 子会话不得修改主对话历史。

### 3.5 工具白名单

- 白名单为空时沿用原 Registry。
- 白名单非空时创建新的 Registry，只保留列出的工具和系统工具。
- 白名单引用未注册工具时抛出 `SkillDependencyError`。
- inline 模式只做启动期依赖校验并在 SOP 顶部提示推荐工具。
- fork 模式使用过滤后的 Registry 实际收窄工具定义。
- `LoadSkill` 是只读系统工具，不受白名单过滤，也不触发权限确认。

### 3.6 命令集成

- Catalog 中每个有效 Skill 自动注册为 `/<name>`。
- 命令说明追加 `[skill]`。
- 与内置命令冲突时跳过 Skill 命令并记录 warning，保留内置命令。
- `/skill` 列出当前 Catalog 的名字、说明、来源、模式和激活项。
- 安装完成后重新扫描 Catalog，并立即刷新 Skill 命令和补全菜单。

### 3.7 远程安装

- `InstallSkill` 是普通写工具，受权限引擎约束。
- 支持 `skills.sh`、GitHub tree URL 和 raw GitHub URL。
- 使用 GitHub Contents API 递归下载，不依赖本地 git。
- 单文件不超过 1 MiB，总大小不超过 8 MiB，文件数不超过 64，目录深度不超过 4。
- 拒绝越界路径、Windows 分隔符路径和非文件/目录条目。
- 暂存目录必须包含有效 `SKILL.md`。
- 安装通过同卷 rename 原子替换；替换失败恢复旧版本。
- 无论成功或失败都清理 staging。

## 4. 非功能需求

- Skill 解析与 Catalog 操作可并发安全读取。
- 错误信息应指出 Skill 名、工具名或远程路径。
- prompt 包不反向依赖 skills 包，通过适配类型传递数据。
- fork 子 Agent 不写入主会话持久化文件。
- 网络异常必须转换为可观察的安装失败结果。

## 5. 边界

本章不实现 Skill 市场、版本解析、升级策略和卸载命令；不扩展第 10 章通用斜杠命令参数语法。

## 6. 验收标准

- 专项测试覆盖解析、加载、覆盖、热重载、激活、工具过滤、两种执行模式和安装安全边界。
- 全量单元测试、Ruff、Mypy、编译检查通过。
- PowerShell 中真实启动 LiCode，可观察 `/help`、Skill 命令、自然语言触发 `LoadSkill`、热更新和 `/clear`。
- 第 11 章形成独立 Git 提交并推送到 `origin/master`。
