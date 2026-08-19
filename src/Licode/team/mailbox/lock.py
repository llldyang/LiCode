"""兼容 mailbox 子包旧导入位置的文件锁导出。"""

from Licode.team.filelock import acquire

__all__ = ["acquire"]
