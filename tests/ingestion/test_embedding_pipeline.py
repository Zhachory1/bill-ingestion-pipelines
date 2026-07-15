import httpx
import pytest
from unittest.mock import patch
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.db import models  # noqa
from app.ingestion.embedding_pipeline import EmbeddingPipeline

FAKE_DIM = 4  # tiny for tests


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_bill(db, bill_id: str, title: str = "T", summary: str = "S", text_url: str | None = None):
    bill = models.Bill(
        bill_id=bill_id, congress=118, bill_type="hr",
        bill_number=int(bill_id.split("-")[-1]),
        title=title, summary=summary, latest_action="", latest_action_date="2023-01-01",
        last_updated="2023-01-01", text_url=text_url,
    )
    db.add(bill)
    db.commit()
    return bill


@pytest.fixture
def mock_encoder():
    """Patch SentenceTransformer so tests don't load a real model."""
    with patch("app.ingestion.embedding_pipeline.SentenceTransformer") as MockST:
        instance = MockST.return_value
        instance.encode.side_effect = lambda texts, **kwargs: np.ones(
            (len(texts), FAKE_DIM), dtype=np.float32
        )
        yield instance


def _encoded_texts(mock_encoder) -> list[str]:
    return [text for call in mock_encoder.encode.call_args_list for text in call[0][0]]


def test_embeds_bills_with_null_embedding(db, mock_encoder):
    _make_bill(db, "118-hr-1")
    _make_bill(db, "118-hr-2")

    pipeline = EmbeddingPipeline(db=db, batch_size=10)
    stats = pipeline.run()

    assert stats["embedded"] == 2
    assert db.query(models.Bill).filter(models.Bill.embedding.is_(None)).count() == 0


def test_skips_already_embedded_bills(db, mock_encoder):
    bill = _make_bill(db, "118-hr-1")
    bill.embedding = [0.1, 0.2, 0.3, 0.4]
    db.commit()
    _make_bill(db, "118-hr-2")  # no embedding

    pipeline = EmbeddingPipeline(db=db, batch_size=10)
    stats = pipeline.run()

    assert stats["embedded"] == 1  # only the null one


def test_batch_processing(db, mock_encoder):
    for i in range(1, 6):
        _make_bill(db, f"118-hr-{i}")

    pipeline = EmbeddingPipeline(db=db, batch_size=2)
    stats = pipeline.run()

    assert stats["embedded"] == 5
    assert mock_encoder.encode.call_count == 3  # ceil(5/2) batches


def test_creates_full_text_chunk_embeddings(db, mock_encoder):
    _make_bill(
        db,
        "118-hr-1",
        title="Climate Bill",
        summary="Reduces emissions.",
        text_url="https://example.com/bill.xml",
    )

    with patch(
        "app.ingestion.embedding_pipeline.fetch_cached_bill_text",
        return_value="Section 1. Full climate resilience language.",
    ):
        pipeline = EmbeddingPipeline(db=db, batch_size=10)
        stats = pipeline.run()

    assert stats["embedded"] == 1
    assert stats["chunks_embedded"] == 1
    assert _encoded_texts(mock_encoder) == [
        "Climate Bill Reduces emissions.",
        "Section 1. Full climate resilience language.",
    ]

    chunk = db.query(models.BillTextChunk).filter_by(bill_id="118-hr-1").one()
    assert chunk.chunk_index == 0
    assert chunk.text == "Section 1. Full climate resilience language."
    assert chunk.source_url == "https://example.com/bill.xml"
    assert chunk.embedding == [1.0] * FAKE_DIM


def test_fallback_text_when_no_title_or_summary(db, mock_encoder):
    bill = models.Bill(
        bill_id="118-hr-99", congress=118, bill_type="hr", bill_number=99,
        title=None, summary=None, latest_action="", latest_action_date="2023-01-01",
        last_updated="2023-01-01",
    )
    db.add(bill)
    db.commit()

    pipeline = EmbeddingPipeline(db=db, batch_size=10)
    pipeline.run()

    texts_passed = mock_encoder.encode.call_args_list[0][0][0]
    assert texts_passed[0] == "118-hr-99"  # falls back to bill_id


def test_full_text_fetch_failure_keeps_metadata_embedding(db, mock_encoder):
    _make_bill(db, "118-hr-1", title="Title", summary="Summary", text_url="https://example.com/bill.xml")

    with patch(
        "app.ingestion.embedding_pipeline.fetch_cached_bill_text",
        side_effect=httpx.HTTPError("boom"),
    ):
        pipeline = EmbeddingPipeline(db=db, batch_size=10)
        stats = pipeline.run()

    assert stats["embedded"] == 1
    assert stats["chunks_embedded"] == 0
    assert stats["full_text_fetch_failures"] == 1
    assert _encoded_texts(mock_encoder) == ["Title Summary"]
    assert db.query(models.BillTextChunk).count() == 0


def test_chunk_text_splits_long_full_text(db):
    pipeline = EmbeddingPipeline(db=db, chunk_size=20, chunk_overlap=5)

    chunks = pipeline._chunk_text("Section one text. Section two text. Section three text.")

    assert len(chunks) > 1
    assert all(len(chunk) <= 20 for chunk in chunks)
    assert "Section one text." in chunks[0]


def test_bill_text_chunk_model_round_trips_in_sqlite(db):
    bill = models.Bill(bill_id="118-hr-101", congress=118, bill_type="hr", bill_number=101)
    chunk = models.BillTextChunk(
        bill_id="118-hr-101",
        chunk_index=0,
        text="full legislative text",
        source_url="https://example.com/bill.xml",
        embedding=[0.1] * 384,
    )
    bill.text_chunks.append(chunk)
    db.add(bill)
    db.commit()

    saved = db.query(models.BillTextChunk).filter_by(bill_id="118-hr-101").one()
    assert saved.text == "full legislative text"
    assert saved.embedding == [0.1] * 384
