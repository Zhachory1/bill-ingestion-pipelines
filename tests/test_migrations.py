from pathlib import Path


def test_embedding_hnsw_migration_is_postgres_only():
    migration = Path("alembic/versions/8f3c2d1e9a0b_add_hnsw_index_for_bill_embeddings.py").read_text()

    assert 'bind.dialect.name != "postgresql"' in migration
    assert "USING hnsw" in migration
    assert "vector_cosine_ops" in migration
    assert "ANALYZE bills" in migration
