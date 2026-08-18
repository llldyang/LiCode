"""上下文管理使用的固定阈值。"""

# 单条工具结果落盘阈值，单位为 UTF-8 字节。
SINGLE_RESULT_LIMIT = 50000
# 单条工具消息的结果聚合阈值，单位为 UTF-8 字节。
MESSAGE_AGGREGATE_LIMIT = 200000
# 摘要请求预留的输出 token。
SUMMARY_RESERVE = 20000
# 自动压缩预留的估算误差与单轮波动 token。
AUTO_SAFETY_MARGIN = 13000
# 手动与紧急压缩使用的安全余量 token。
MANUAL_SAFETY_MARGIN = 3000
# 恢复段最多包含的最近文件数。
RECOVERY_FILE_LIMIT = 5
# 恢复段中单个文件最多保留的估算 token。
RECOVERY_TOKENS_PER_FILE = 5000
# 摘要后近期原文至少保留的估算 token。
RECENT_KEEP_TOKENS = 10000
# 摘要后近期原文至少保留的消息数。
RECENT_KEEP_MESSAGES = 5
# 自动摘要连续失败后的熔断阈值。
MAX_CONSECUTIVE_AUTO_COMPACT_FAILURES = 3
# 摘要请求过长时逐组丢弃的直接重试次数。
PTL_RETRY_LIMIT = 3
# 直接重试用完后每次丢弃的消息组比例。
PTL_DROP_PERCENTAGE = 0.2
# 字符数换算 token 的近似比例。
ESTIMATE_CHARS_PER_TOKEN = 3.5
# 工具结果预览头部的 UTF-8 字节上限。
PREVIEW_HEAD_BYTES = 2048
# 工具结果预览头部的行数上限。
PREVIEW_HEAD_LINES = 20
