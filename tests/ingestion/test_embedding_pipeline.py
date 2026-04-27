import pytest
from unittest.mock import patch, MagicMock
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


def _make_bill(db, bill_id: str, title: str = "T", summary: str = "S"):
    bill = models.Bill(
        bill_id=bill_id, congress=118, bill_type="hr",
        bill_number=int(bill_id.split("-")[-1]),
        title=title, summary=summary, latest_action="", latest_action_date="2023-01-01",
        last_updated="2023-01-01",
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


def test_text_construction_title_plus_summary(db, mock_encoder):
    _make_bill(db, "118-hr-1", title="Climate Bill", summary="Reduces emissions.")

    pipeline = EmbeddingPipeline(db=db, batch_size=10)
    pipeline.run()

    calls = mock_encoder.encode.call_args_list
    assert len(calls) == 1
    texts_passed = calls[0][0][0]  # positional arg: list of texts
    assert texts_passed[0] == "Climate Bill Reduces emissions."


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
