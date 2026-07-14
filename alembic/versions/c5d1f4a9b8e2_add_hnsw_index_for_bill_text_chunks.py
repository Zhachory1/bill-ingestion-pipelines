"""add hnsw index for bill text chunks

Revision ID: c5d1f4a9b8e2
Revises: 7ab4c9d0e1f2, 8f3c2d1e9a0b
Create Date: 2026-07-14
"""

from typing import Sequence, Union
from alembic import op

revision: str = "c5d1f4a9b8e2"
down_revision: Union[str, tuple[str, str], None] = ("7ab4c9d0e1f2", "8f3c2d1e9a0b")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bill_text_chunks_embedding_hnsw "
        "ON bill_text_chunks USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute("ANALYZE bill_text_chunks")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_bill_text_chunks_embedding_hnsw")
