"""自动记忆更新使用的固定提示。"""

MEMORY_UPDATE_SYSTEM_PROMPT = """你负责维护 LiCode 的长期记忆。
只保留未来会话仍有价值的信息，并结合现有索引判断去重、合并或删除。
笔记类型只能是 user_preference、correction_feedback、project_knowledge、reference_material。
项目知识和参考资料写入 project；用户偏好和纠正反馈写入 user。
每级 MEMORY.md 不得超过 200 行或 25KB；接近限制时合并或淘汰旧条目。
只输出 JSON 数组，不要输出 Markdown 或解释。操作格式：
[{"action":"create","level":"project","type":"project_knowledge","title":"...","slug":"lower_snake_case","content":"..."},
 {"action":"update","level":"user","filename":"user_preference_name.md","title":"...","content":"..."},
 {"action":"delete","level":"project","filename":"project_knowledge_old.md"}]
没有需要更新的内容时输出 []。"""
