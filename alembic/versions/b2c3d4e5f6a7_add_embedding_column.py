"""add embedding column

Revision ID: b2c3d4e5f6a7
Revises: 21a38ea0e61a
Create Date: 2026-04-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = '21a38ea0e61a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column('bills', sa.Column('embedding', Vector(384), nullable=True))


def downgrade() -> None:
    op.drop_column('bills', 'embedding')
