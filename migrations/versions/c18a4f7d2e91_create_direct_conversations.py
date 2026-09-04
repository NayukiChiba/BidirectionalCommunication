"""创建一对一会话、成员关系并迁移消息归属

Revision ID: c18a4f7d2e91
Revises: f53ad4a832a9
Create Date: 2026-09-04 14:30:00

"""

from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c18a4f7d2e91"
down_revision: str | Sequence[str] | None = "f53ad4a832a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建会话结构并把旧消息按成员组合归入稳定会话。"""
    op.create_table(
        "conversations",
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("member_pair_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(conversation_id) = 36",
            name="ck_conversations_id_length",
        ),
        sa.CheckConstraint(
            "length(trim(member_pair_key)) > 2",
            name="ck_conversations_member_pair_key_not_blank",
        ),
        sa.PrimaryKeyConstraint("conversation_id"),
        sa.UniqueConstraint(
            "member_pair_key",
            name="uq_conversations_member_pair_key",
        ),
    )
    op.create_table(
        "conversation_members",
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("member_position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "member_position IN (1, 2)",
            name="ck_conversation_members_position",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.conversation_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("conversation_id", "user_id"),
        sa.UniqueConstraint(
            "conversation_id",
            "member_position",
            name="uq_conversation_members_position",
        ),
    )

    with op.batch_alter_table("messages") as batchOp:
        batchOp.add_column(
            sa.Column("conversation_id", sa.String(length=36), nullable=True)
        )

    _backfillExistingMessages()

    op.drop_index(
        "ix_messages_sender_recipient_created_message",
        table_name="messages",
    )
    with op.batch_alter_table("messages") as batchOp:
        batchOp.alter_column(
            "conversation_id",
            existing_type=sa.String(length=36),
            nullable=False,
        )
        batchOp.create_foreign_key(
            "fk_messages_conversation_id_conversations",
            "conversations",
            ["conversation_id"],
            ["conversation_id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_messages_conversation_created_message",
        "messages",
        ["conversation_id", "created_at", "message_id"],
        unique=False,
    )


def _backfillExistingMessages() -> None:
    """为迁移前的双向消息创建确定性的会话和成员记录。"""
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT sender_id, recipient_id, MIN(created_at) AS created_at "
            "FROM messages GROUP BY sender_id, recipient_id"
        )
    ).mappings()
    pairCreatedAt: dict[tuple[str, str], object] = {}
    for row in rows:
        senderId = str(row["sender_id"])
        recipientId = str(row["recipient_id"])
        if senderId == recipientId:
            raise RuntimeError("无法迁移自发消息：一对一会话必须包含两名不同用户")
        pair = tuple(sorted((senderId, recipientId)))
        currentCreatedAt = pairCreatedAt.get(pair)
        if currentCreatedAt is None or row["created_at"] < currentCreatedAt:
            pairCreatedAt[pair] = row["created_at"]

    if not pairCreatedAt:
        return

    existingUserIds = set(
        connection.execute(sa.text("SELECT user_id FROM users")).scalars()
    )
    missingUserIds = {
        userId
        for pair in pairCreatedAt
        for userId in pair
        if userId not in existingUserIds
    }
    if missingUserIds:
        raise RuntimeError(
            "无法迁移消息：存在尚未注册的发送者或接收者，请先清理旧测试数据"
        )

    for pair, createdAt in pairCreatedAt.items():
        pairKey = ":".join(pair)
        conversationId = str(uuid5(NAMESPACE_URL, f"direct-conversation:{pairKey}"))
        connection.execute(
            sa.text(
                "INSERT INTO conversations "
                "(conversation_id, member_pair_key, created_at) "
                "VALUES (:conversationId, :pairKey, :createdAt)"
            ),
            {
                "conversationId": conversationId,
                "pairKey": pairKey,
                "createdAt": createdAt,
            },
        )
        for position, userId in enumerate(pair, start=1):
            connection.execute(
                sa.text(
                    "INSERT INTO conversation_members "
                    "(conversation_id, user_id, member_position) "
                    "VALUES (:conversationId, :userId, :position)"
                ),
                {
                    "conversationId": conversationId,
                    "userId": userId,
                    "position": position,
                },
            )
        connection.execute(
            sa.text(
                "UPDATE messages SET conversation_id = :conversationId "
                "WHERE (sender_id = :firstId AND recipient_id = :secondId) "
                "OR (sender_id = :secondId AND recipient_id = :firstId)"
            ),
            {
                "conversationId": conversationId,
                "firstId": pair[0],
                "secondId": pair[1],
            },
        )


def downgrade() -> None:
    """恢复按发送者和接收者查询消息的旧结构。"""
    op.drop_index(
        "ix_messages_conversation_created_message",
        table_name="messages",
    )
    with op.batch_alter_table("messages") as batchOp:
        batchOp.drop_constraint(
            "fk_messages_conversation_id_conversations",
            type_="foreignkey",
        )
        batchOp.drop_column("conversation_id")
    op.create_index(
        "ix_messages_sender_recipient_created_message",
        "messages",
        ["sender_id", "recipient_id", "created_at", "message_id"],
        unique=False,
    )
    op.drop_table("conversation_members")
    op.drop_table("conversations")
