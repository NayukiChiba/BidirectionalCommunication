"""用户、会话与消息领域异常。"""


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


class InvalidConversationId(DomainError):
    """会话标识不合法。"""


class InvalidConversation(DomainError):
    """一对一会话没有满足成员不变量。"""


class ConversationMemberRequired(DomainError):
    """用户不是当前会话成员。"""


class InvalidMessagePosition(DomainError):
    """累计消息位置不合法。"""


class ReadPositionBeyondDelivery(DomainError):
    """已读位置超过当前已送达位置。"""
