"""应用层异常。"""


class MessageStorageError(RuntimeError):
    """消息无法通过存储端口保存。"""
