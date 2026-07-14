from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory


def test_alembic_has_single_head():
    script = ScriptDirectory.from_config(Config("alembic.ini"))

    assert len(script.get_heads()) == 1


def test_embedding_hnsw_migration_is_postgres_only():
    migration = Path("alembic/versions/8f3c2d1e9a0b_add_hnsw_index_for_bill_embeddings.py").read_text()

    assert 'bind.dialect.name != "postgresql"' in migration
    assert "USING hnsw" in migration
    assert "vector_cosine_ops" in migration
    assert "ANALYZE bills" in migration


def test_chunk_embedding_hnsw_migration_is_postgres_only():
    migration = Path("alembic/versions/c5d1f4a9b8e2_add_hnsw_index_for_bill_text_chunks.py").read_text()

    assert 'bind.dialect.name != "postgresql"' in migration
    assert "ON bill_text_chunks USING hnsw" in migration
    assert "vector_cosine_ops" in migration
    assert "ANALYZE bill_text_chunks" in migration
