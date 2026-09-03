"""应用层异常。"""


class MessageStorageError(RuntimeError):
    """消息无法通过存储端口保存。"""


class MessageStorageConflictError(MessageStorageError):
    """消息写入与数据库唯一约束冲突。"""


class InvalidMessageHistoryQuery(ValueError):
    """历史消息查询参数不满足应用规则。"""
