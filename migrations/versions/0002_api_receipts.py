"""Persist successful channel requests for retry safety."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "api_receipts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("principal", sa.String(150), nullable=False),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("response", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("principal", "key", name="uq_api_receipt"),
    )


def downgrade():
    op.drop_table("api_receipts")
