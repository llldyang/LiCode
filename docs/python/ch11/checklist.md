# 第 11 章：Skill 系统 Checklist

## 1. 解析与加载

- [x] frontmatter 与正文可正确拆分。
- [x] name、mode、fork_context 和 allowed_tools 会校验。
- [x] 支持 `<name>.md` 与 `<name>/SKILL.md`。
- [x] 项目级同名 Skill 覆盖用户级。
- [x] 单个坏文件不阻断 Catalog。
- [x] get 每次重读，坏更新回退缓存。
- [x] source label 返回 project/user。

## 2. 执行与工具

- [x] `$ARGUMENTS` 全量替换。
- [x] inline 激活正文并触发主 Agent。
- [x] fork 支持 none/recent/full。
- [x] fork 使用独立会话和 runtime。
- [x] fork 结果回流且不污染主历史。
- [x] 白名单缺工具立即报错。
- [x] 系统工具不被白名单移除。
- [x] LoadSkill 是只读系统工具且不弹审批。

## 3. Prompt 与状态

- [x] system prompt 只注入 Skill 名字和说明。
- [x] Agent 会看到 LoadSkill 调用指引。
- [x] 完整 SOP 出现在 `## Active Skills`。
- [x] 多个 Skill 可同时激活。
- [x] 重复激活同名 Skill 原位更新。
- [x] `/clear` 和新会话清空激活态。

## 4. 命令与热更新

- [x] `/skill` 出现在 `/help`。
- [x] Skill 自动注册为 `/name`，说明含 `[skill]`。
- [x] Skill 与内置命令冲突时 warning 并保留内置命令。
- [x] 修改 `SKILL.md` 后无需重启即可生效。
- [x] 安装后 Catalog、命令和补全立即刷新。

## 5. 远程安装

- [x] 支持 skills.sh URL。
- [x] 支持 GitHub tree URL。
- [x] 支持 raw.githubusercontent.com URL。
- [x] 使用 GitHub Contents API。
- [x] 单文件限制 1 MiB。
- [x] 总大小限制 8 MiB。
- [x] 文件数限制 64。
- [x] 递归深度限制 4。
- [x] 拒绝越界和平台分隔符路径。
- [x] 缺少 `SKILL.md` 时拒绝并清理 staging。
- [x] 原子替换失败恢复旧版本。
- [x] 网络异常返回工具错误。

## 6. 自动化检查

- [x] `uv run pytest tests/test_skills.py -q` 通过。
- [x] `uv run pytest -q` 通过。
- [x] `uv run ruff check src/Licode tests` 通过。
- [x] `uv run ruff format --check src/Licode tests` 通过。
- [x] `uv run mypy src/Licode` 通过。
- [x] `uv run python -m compileall -q src/Licode tests` 通过。
- [x] `git diff --check` 通过。

## 7. PowerShell 端到端

- [x] PowerShell 启动 LiCode 成功。
- [x] `/help` 显示 `/skill` 和测试 Skill。
- [x] 显式 Skill 命令触发真实 Agent 回复。
- [x] 修改 Skill 后不重启可观察到新 SOP。
- [x] 自然语言请求使模型调用 LoadSkill。
- [x] LoadSkill 调用没有权限确认。
- [x] `/clear` 后旧 Active Skills 不再注入。
- [x] 坏 Skill 只产生 warning，其他 Skill 正常。
- [x] fork Skill 独立执行并把结果回流主会话。

## 8. Git

- [x] 第 11 章使用独立 commit。
- [x] commit 推送到 `origin/master`。
- [x] 远端完整哈希与本地 HEAD 一致。
