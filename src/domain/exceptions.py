"""消息领域异常。"""


class DomainError(ValueError):
    """领域规则被违反。"""


class InvalidUserId(DomainError):
    """用户标识不合法。"""


class InvalidUsername(DomainError):
    """用户名不符合领域规则。"""


class InvalidPasswordHash(DomainError):
    """密码哈希不符合领域规则。"""


class InvalidUser(DomainError):
    """用户实体组合不符合领域规则。"""


class InvalidMessageId(DomainError):
    """服务端消息标识不合法。"""


class InvalidClientMessageId(DomainError):
    """客户端消息标识不合法。"""


class InvalidMessageContent(DomainError):
    """消息内容不合法。"""


class InvalidMessageCreatedAt(DomainError):
    """消息创建时间不合法。"""


class InvalidChatMessage(DomainError):
    """聊天消息没有由合法领域概念组成。"""
