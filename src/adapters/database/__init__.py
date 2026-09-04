"""异步 SQLAlchemy 数据库基础设施公开接口。"""

from src.adapters.database.asyncSqlAlchemyMessageRepository import (
    AsyncSqlAlchemyMessageRepository,
)
from src.adapters.database.asyncSqlAlchemyMessageUnitOfWork import (
    AsyncSqlAlchemyMessageUnitOfWork,
    AsyncSqlAlchemyMessageUnitOfWorkFactory,
)
from src.adapters.database.asyncSqlAlchemyUserRepository import (
    AsyncSqlAlchemyUserRepository,
)
from src.adapters.database.asyncSqlAlchemyUserUnitOfWork import (
    AsyncSqlAlchemyUserUnitOfWork,
    AsyncSqlAlchemyUserUnitOfWorkFactory,
)
from src.adapters.database.connection import (
    createAsyncSessionFactory,
    createAsyncSqliteEngine,
    createAsyncSqliteUrl,
)
from src.adapters.database.messageMapper import toDomainMessage, toMessageRecord
from src.adapters.database.models import DatabaseBase, MessageRecord, UserRecord
from src.adapters.database.userMapper import toDomainUser, toUserRecord

__all__ = [
    "AsyncSqlAlchemyMessageRepository",
    "AsyncSqlAlchemyMessageUnitOfWork",
    "AsyncSqlAlchemyMessageUnitOfWorkFactory",
    "AsyncSqlAlchemyUserRepository",
    "AsyncSqlAlchemyUserUnitOfWork",
    "AsyncSqlAlchemyUserUnitOfWorkFactory",
    "DatabaseBase",
    "MessageRecord",
    "UserRecord",
    "createAsyncSessionFactory",
    "createAsyncSqliteEngine",
    "createAsyncSqliteUrl",
    "toDomainMessage",
    "toDomainUser",
    "toMessageRecord",
    "toUserRecord",
]
