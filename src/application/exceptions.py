"""应用层异常。"""


class MessageStorageError(RuntimeError):
    """消息无法通过存储端口保存。"""


class MessageStorageConflictError(MessageStorageError):
    """消息写入与数据库唯一约束冲突。"""


class InvalidMessageHistoryQuery(ValueError):
    """历史消息查询参数不满足应用规则。"""


class AuthenticationError(ValueError):
    """身份认证流程失败。"""


class InvalidRegistration(AuthenticationError):
    """注册输入不符合应用规则。"""


class UsernameAlreadyExists(AuthenticationError):
    """规范化用户名已经被注册。"""


class InvalidCredentials(AuthenticationError):
    """用户名、密码或访问令牌不能建立身份。"""


class InvalidAccessToken(InvalidCredentials):
    """访问令牌无效、过期或缺少必要声明。"""


class UserStorageError(RuntimeError):
    """用户无法通过持久化端口读取或保存。"""


class InvalidConversationRequest(ValueError):
    """创建会话的输入不满足业务规则。"""


class ConversationUnavailable(LookupError):
    """会话不存在或当前用户不是成员。"""


class ConversationStorageError(RuntimeError):
    """会话无法通过持久化端口读取或保存。"""


class ConversationStorageConflictError(ConversationStorageError):
    """会话成员组合与数据库唯一约束冲突。"""
