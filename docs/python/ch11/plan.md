# 第 11 章：Skill 系统 Plan

## 1. 架构概览

本章新增 `Licode.skills` 核心包，并通过窄接口接入现有 Agent、Prompt、Tool、Command 和 TUI。

```text
CLI
 |- Catalog.load(work_dir)
 |- register LoadSkill / InstallSkill
 |- validate allowed_tools
 `- LiCodeApp(catalog, install_tool)
       |- register Skill slash commands
       |- Executor(inline / fork)
       `- Agent.with_catalog(catalog)

Agent loop
 |- stable system: Available Skills
 |- dynamic environment: Active Skills
 `- tool execution: LoadSkill activates latest SOP
```

## 2. 组件划分

### 2.1 `Licode.skills`

- `types.py`：`SkillMeta`、`Skill`、`SkillSource`、摘要和校验问题。
- `parser.py`：frontmatter 分离、元数据校验、文件/目录解析、参数替换。
- `catalog.py`：两级扫描、覆盖、缓存、热重载、依赖校验。
- `active.py`：会话级激活列表和子 Agent ContextVar 绑定。
- `render.py`：参数替换、用户请求追加、工具提示前缀。
- `adapter.py`：转换为 prompt 包的只读数据类型。
- `executor.py`：inline/fork 分发、历史构造、provider 选择、子 Agent 生命周期。
- `install.py`：URL 解析、Contents API 下载、限额、路径防护和原子替换。

### 2.2 Tool

- `LoadSkillTool`：`read_only=True`、`is_system=True`，只返回简短确认。
- `InstallSkillTool`：`read_only=False`，安装后触发命令刷新回调。
- `Registry`：增加 `items`、`system_definitions` 和 `definitions_filtered`。
- 所有现有工具和 MCP 工具显式声明 `is_system=False`。

### 2.3 Prompt 与 Agent

- system prompt priority 90 放置 Catalog 摘要，保持稳定前缀。
- environment 每轮拼接激活 SOP，确保工具调用后的下一轮立即可见。
- `SessionRuntime.active_skills` 作为会话级状态。
- `Agent.run` 绑定当前 runtime 的 ActiveSkills，使 fork 中复用的 `LoadSkillTool` 激活子 runtime。

### 2.4 Command 与 TUI

- 新增 `/skill` 本地命令。
- 启动时注册 Catalog 中所有无冲突 Skill。
- Skill 命令 handler 捕获固定名称，避免循环闭包引用错误。
- TUI 持有 Catalog 和 Executor，并在 provider 激活/会话重置时重新绑定执行上下文。
- 安装回调先移除旧 Skill 命令，再按最新 Catalog 注册并刷新补全。

## 3. 核心数据结构

```python
@dataclass(frozen=True, slots=True)
class SkillMeta:
    name: str
    description: str
    allowed_tools: list[str]
    mode: Literal["inline", "fork"]
    fork_context: Literal["none", "recent", "full"]
    model: str | None


@dataclass(frozen=True, slots=True)
class Skill:
    meta: SkillMeta
    prompt_body: str
    source_dir: Path
    source_path: Path
    source: SkillSource
    is_directory: bool
```

`ActiveSkills` 使用有序列表保存激活顺序，并用 name 到索引的映射支持原位覆盖。内部用 `RLock` 保护快照和修改。

`Catalog` 保存：

- `_by_name`：当前有效定义。
- `_cache`：最近一次有效定义。
- `_order`：按 name 排序的稳定列表。
- `_project_dir` / `_user_dir`：来源目录。

## 4. 模块交互

### 4.1 启动

1. CLI 加载配置、会话、权限和 MCP 工具。
2. `Catalog.load(root)` 扫描用户级和项目级 Skill。
3. 注册 `LoadSkillTool` 和 `InstallSkillTool`。
4. `Catalog.validate_tools(registry)` 检查白名单；无效 Skill 从本次 Catalog 移除。
5. TUI 构造 Executor，注册内置命令和 Skill 命令。
6. provider 激活时构造 Agent，并调用 `with_catalog`。

### 4.2 自然语言激活

1. Agent 从 `Available Skills` 判断命中项。
2. 模型调用 `LoadSkill({"name": ...})`。
3. Tool 通过 `Catalog.get` 重读文件，把正文写入当前 ActiveSkills。
4. 下一轮 environment 出现完整 SOP。
5. Tool 为只读系统工具，权限引擎直接允许。

### 4.3 inline 命令

1. `/<name>` 命中动态注册 handler。
2. Executor 热重载 Skill 并执行 `render_body`。
3. 正文写入主 runtime 的 ActiveSkills。
4. UI 注入提示并启动主 Agent。
5. 后续回复写入主 Conversation。

### 4.4 fork 命令

1. Executor 按 `fork_context` 深拷贝或汇总历史。
2. `filter_tool_registry` 创建过滤视图。
3. 选择主 provider 或指定 provider。
4. 在临时目录构建独立 runtime 和 Agent。
5. 完整消费 Agent 异步生成器，避免 ContextVar 跨上下文回收。
6. 聚合文本并通过 UI 写回主对话。

### 4.5 安装

1. 解析 URL 为 owner/repo/ref/path。
2. 在安装根目录同级创建 staging。
3. 递归调用 Contents API，逐条校验类型、路径和限额。
4. 校验并解析 staging 中的 `SKILL.md`。
5. 旧目录临时改名为 backup，staging rename 到目标。
6. 失败恢复 backup；成功删除 backup。
7. Catalog reload，TUI 回调刷新命令。
8. finally 清理临时目录。

## 5. 技术决策

| 决策点 | 选择 | 原因 |
|---|---|---|
| Catalog 优先级 | 用户先扫、项目后覆盖 | 项目配置优先 |
| Catalog 注入 | 稳定 system 模块 | 利用 prompt cache |
| Active 注入 | 动态 environment | 工具调用后下一轮立即生效 |
| inline 白名单 | 校验 + SOP 提示 | 不改变主会话工具生命周期 |
| fork 白名单 | 新 Registry 实际过滤 | 子任务边界明确 |
| 系统工具 | `is_system` 豁免 | 支持 Skill 嵌套加载 |
| 命令冲突 | 保留内置命令 | 保护已有命令行为 |
| fork 会话 | 独立 runtime + 临时目录 | 不污染主历史和持久化 |
| 远程下载 | GitHub Contents API | 不依赖本地 git |
| 安装落盘 | 同卷 rename + backup | 支持失败回滚 |

## 6. 文件清单

```text
src/Licode/skills/
src/Licode/tool/load_skill.py
src/Licode/tool/install_skill.py
src/Licode/command/builtin_skill.py
src/Licode/command/skills.py
src/Licode/prompt/skills_block.py
tests/test_skills.py
docs/python/ch11/
```
