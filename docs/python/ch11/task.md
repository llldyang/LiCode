# 第 11 章：Skill 系统 Task

## T1 数据结构与解析

- [x] 定义 `SkillMeta`、`Skill`、`SkillSource`。
- [x] 解析 YAML frontmatter 和 Markdown 正文。
- [x] 校验 name、mode、fork_context、model、allowed_tools。
- [x] 支持单文件与目录型布局。
- [x] 实现 `$ARGUMENTS` 替换。
- 验证：parser 有效与无效输入专项测试。

## T2 Catalog 与热重载

- [x] 扫描 `~/.LiCode/skills` 和项目 `.LiCode/skills`。
- [x] 项目定义覆盖同名用户定义。
- [x] 单项解析失败 warning 后跳过。
- [x] 每次 get 重读文件，失败回退缓存。
- [x] 提供列表、来源、reload 差异与工具校验。
- 验证：覆盖、坏文件、成功/失败热重载测试。

## T3 激活态与 Prompt

- [x] 实现有序、可覆盖、并发安全的 ActiveSkills。
- [x] 渲染 Available Skills Catalog。
- [x] 渲染 Active Skills environment block。
- [x] SessionRuntime 新会话清理激活态。
- 验证：渲染与状态测试、Agent 请求捕获。

## T4 工具白名单

- [x] Tool Protocol 增加系统工具标记。
- [x] Registry 支持系统工具和白名单定义导出。
- [x] 实现 `filter_tool_registry`。
- [x] 缺失工具抛出依赖错误。
- 验证：空白名单、过滤、系统豁免、缺失工具测试。

## T5 LoadSkill

- [x] 实现只读系统工具。
- [x] 按 name 热重载并激活正文。
- [x] 未知 Skill 返回 Catalog 名单。
- [x] 子 Agent 通过 ContextVar 激活自己的 runtime。
- 验证：直接工具测试和 Agent 两轮工具调用测试。

## T6 Executor inline

- [x] 热重载并渲染正文。
- [x] 激活 SOP。
- [x] 通过 UI 注入触发主 Agent。
- 验证：动态 Skill 命令执行测试。

## T7 Executor fork

- [x] 支持 none/recent/full 历史策略。
- [x] 支持工具过滤和指定 provider。
- [x] 创建独立 Conversation、Runtime、临时目录。
- [x] 完整消费子 Agent 事件并聚合文本。
- [x] 错误转为可观察结果。
- 验证：历史构造、工具列表、主会话隔离测试。

## T8 命令与 TUI

- [x] 注册 `/skill`。
- [x] Catalog Skill 注册为动态斜杠命令。
- [x] 冲突时保留内置命令并 warning。
- [x] `/clear` 清理激活状态。
- [x] 安装后刷新命令和补全。
- 验证：命令 Registry、TUI 既有回归测试。

## T9 Agent 与 CLI 接线

- [x] CLI 构造 Catalog 并注册两个工具。
- [x] 启动时校验工具依赖。
- [x] Agent 注入 Catalog 与 Active Skills。
- [x] TUI 在 provider/Conversation 变化时绑定 Executor。
- 验证：Agent 请求内容测试、全量回归。

## T10 远程安装

- [x] 支持三类 URL。
- [x] 使用 Contents API 递归下载。
- [x] 实现文件、总量、数量、深度限制。
- [x] 实现路径穿越防护。
- [x] 实现 staging、原子替换和失败回滚。
- [x] 安装后 reload 和回调。
- 验证：URL、下载、限额、清理、回滚、回调测试。

## T11 自动化验证

- [x] 新增 `tests/test_skills.py`。
- [x] 全量 pytest、Ruff、Mypy、compileall、diff check 通过。
- 验证：章节结束前执行统一质量门禁。

## T12 PowerShell 端到端与 Git

- [x] 启动 LiCode 并输入真实请求。
- [x] 验证显式命令、自然语言工具调用、热更新和 clear。
- [x] 对照 checklist 验收。
- [x] 创建第 11 章独立提交并推送。
