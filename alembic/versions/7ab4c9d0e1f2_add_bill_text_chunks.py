"""add bill text chunks

Revision ID: 7ab4c9d0e1f2
Revises: a9a1e0d64a15
Create Date: 2026-06-29
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from app.config import settings

revision: str = "7ab4c9d0e1f2"
down_revision: Union[str, None] = "a9a1e0d64a15"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bill_text_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("bill_id", sa.String(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(settings.EMBEDDING_DIM), nullable=True),
        sa.ForeignKeyConstraint(["bill_id"], ["bills.bill_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bill_id", "chunk_index", name="uq_bill_text_chunk"),
    )
    op.create_index("ix_bill_text_chunks_bill_id", "bill_text_chunks", ["bill_id"])


def downgrade() -> None:
    op.drop_index("ix_bill_text_chunks_bill_id", table_name="bill_text_chunks")
    op.drop_table("bill_text_chunks")
