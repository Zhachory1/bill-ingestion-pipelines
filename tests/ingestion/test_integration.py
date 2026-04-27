"""Integration test: runs the full Universe DL pipeline on a small fixture corpus."""
import shutil
import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.db import models  # noqa
from app.ingestion.universe_dl import UniverseDL

FIXTURE = Path(__file__).parent / "fixtures" / "sample_billstatus.xml"


def _make_xml(congress: int, bill_type: str, number: int) -> str:
    """Generate a minimal valid BILLSTATUS XML with a unique bill identity."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<billStatus>
  <bill>
    <type>{bill_type.upper()}</type>
    <number>{number}</number>
    <congress>{congress}</congress>
    <title>A Bill {congress}-{bill_type}-{number}</title>
    <updateDate>2023-01-15T10:00:00Z</updateDate>
    <sponsors/>
    <cosponsors/>
    <actions>
      <item><actionDate>2023-01-15</actionDate><text>Introduced</text></item>
    </actions>
    <summaries/>
  </bill>
</billStatus>"""


@pytest.fixture
def corpus(tmp_path):
    """Build a mini corpus: 3 valid bills with distinct IDs + 1 invalid XML."""
    for congress, bill_type, number in [(118, "hr", 1), (118, "s", 5), (117, "hr", 100)]:
        path = tmp_path / str(congress) / bill_type / str(number)
        path.mkdir(parents=True)
        (path / "fdsys_billstatus.xml").write_text(_make_xml(congress, bill_type, number))
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "fdsys_billstatus.xml").write_text("<billStatus><bill></bill></billStatus>")
    return tmp_path


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_universe_dl_full_run(db, corpus):
    dl = UniverseDL(db=db, corpus_dir=corpus, batch_size=2)
    stats = dl.run()

    assert stats["processed"] == 3
    assert stats["failed"] == 1
    assert db.query(models.Bill).count() == 3
    assert db.query(models.ParseFailure).count() == 1


def test_universe_dl_is_idempotent(db, corpus):
    """Running twice should not duplicate bills."""
    dl = UniverseDL(db=db, corpus_dir=corpus, batch_size=10)
    dl.run()

    # Clear checkpoint so it re-processes everything
    db.query(models.IngestCheckpoint).delete()
    db.commit()

    dl2 = UniverseDL(db=db, corpus_dir=corpus, batch_size=10)
    dl2.run()

    assert db.query(models.Bill).count() == 3  # still 3, not 6
