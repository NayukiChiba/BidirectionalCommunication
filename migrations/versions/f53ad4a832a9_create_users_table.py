"""创建认证用户表

Revision ID: f53ad4a832a9
Revises: b5db92390df6
Create Date: 2026-09-04 10:45:56.262009

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f53ad4a832a9"
down_revision: str | Sequence[str] | None = "b5db92390df6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建只保存密码哈希的认证用户表。"""
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(password_hash)) > 0",
            name="ck_users_password_hash_not_blank",
        ),
        sa.CheckConstraint(
            "length(user_id) = 36",
            name="ck_users_user_id_length",
        ),
        sa.CheckConstraint(
            "length(username) BETWEEN 3 AND 32",
            name="ck_users_username_length",
        ),
        sa.CheckConstraint(
            "username = lower(trim(username))",
            name="ck_users_username_normalized",
        ),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("username", name="uq_users_username"),
    )


def downgrade() -> None:
    """删除认证用户表。"""
    op.drop_table("users")
