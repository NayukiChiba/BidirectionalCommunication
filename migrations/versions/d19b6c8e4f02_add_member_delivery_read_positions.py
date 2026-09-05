"""增加会话成员累计送达和已读位置

Revision ID: d19b6c8e4f02
Revises: c18a4f7d2e91
Create Date: 2026-09-05 09:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d19b6c8e4f02"
down_revision: str | Sequence[str] | None = "c18a4f7d2e91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """用消息游标对为每名会话成员保存两个累计位置。"""
    with op.batch_alter_table("conversation_members") as batchOp:
        batchOp.add_column(
            sa.Column("delivered_created_at", sa.DateTime(timezone=True), nullable=True)
        )
        batchOp.add_column(
            sa.Column("delivered_message_id", sa.String(length=36), nullable=True)
        )
        batchOp.add_column(
            sa.Column("read_created_at", sa.DateTime(timezone=True), nullable=True)
        )
        batchOp.add_column(
            sa.Column("read_message_id", sa.String(length=36), nullable=True)
        )
        batchOp.create_check_constraint(
            "ck_conversation_members_delivered_pair",
            "(delivered_created_at IS NULL) = (delivered_message_id IS NULL)",
        )
        batchOp.create_check_constraint(
            "ck_conversation_members_read_pair",
            "(read_created_at IS NULL) = (read_message_id IS NULL)",
        )
        batchOp.create_foreign_key(
            "fk_conversation_members_delivered_message",
            "messages",
            ["delivered_message_id"],
            ["message_id"],
            ondelete="RESTRICT",
        )
        batchOp.create_foreign_key(
            "fk_conversation_members_read_message",
            "messages",
            ["read_message_id"],
            ["message_id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    """删除成员累计位置并恢复 Issue 18 的成员结构。"""
    with op.batch_alter_table("conversation_members") as batchOp:
        batchOp.drop_constraint(
            "fk_conversation_members_read_message",
            type_="foreignkey",
        )
        batchOp.drop_constraint(
            "fk_conversation_members_delivered_message",
            type_="foreignkey",
        )
        batchOp.drop_constraint(
            "ck_conversation_members_read_pair",
            type_="check",
        )
        batchOp.drop_constraint(
            "ck_conversation_members_delivered_pair",
            type_="check",
        )
        batchOp.drop_column("read_message_id")
        batchOp.drop_column("read_created_at")
        batchOp.drop_column("delivered_message_id")
        batchOp.drop_column("delivered_created_at")
