"""add hnsw index for bill embeddings

Revision ID: 8f3c2d1e9a0b
Revises: a9a1e0d64a15
Create Date: 2026-06-29
"""

from typing import Sequence, Union
from alembic import op

revision: str = "8f3c2d1e9a0b"
down_revision: Union[str, None] = "a9a1e0d64a15"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_bills_embedding_hnsw "
        "ON bills USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )
    op.execute("ANALYZE bills")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_bills_embedding_hnsw")
