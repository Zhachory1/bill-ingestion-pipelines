import shutil
import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.db import models  # noqa
from app.ingestion.universe_dl import UniverseDL

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def xml_corpus(tmp_path):
    """Create a fake corpus with 2 valid XML files across different directories."""
    (tmp_path / "118/hr/1").mkdir(parents=True)
    (tmp_path / "118/s/1").mkdir(parents=True)
    shutil.copy(FIXTURE_DIR / "sample_billstatus.xml", tmp_path / "118/hr/1/fdsys_billstatus.xml")
    shutil.copy(FIXTURE_DIR / "sample_billstatus.xml", tmp_path / "118/s/1/fdsys_billstatus.xml")
    return tmp_path


def test_finds_all_xml_files(db, xml_corpus):
    dl = UniverseDL(db=db, corpus_dir=xml_corpus, batch_size=10)
    files = dl._enumerate_xml_files()
    assert len(files) == 2


def test_processes_all_files(db, xml_corpus):
    dl = UniverseDL(db=db, corpus_dir=xml_corpus, batch_size=10)
    stats = dl.run()
    assert stats["processed"] == 2
    assert stats["failed"] == 0


def test_failed_parse_logged_to_db(db, tmp_path):
    bad_xml = tmp_path / "bad.xml"
    bad_xml.write_text("<billStatus><bill></bill></billStatus>")
    dl = UniverseDL(db=db, corpus_dir=tmp_path, batch_size=10)
    stats = dl.run()
    assert stats["failed"] == 1
    assert db.query(models.ParseFailure).count() == 1


def test_checkpoint_saved_per_batch(db, xml_corpus):
    dl = UniverseDL(db=db, corpus_dir=xml_corpus, batch_size=1)
    dl.run()
    checkpoint = db.query(models.IngestCheckpoint).filter_by(pipeline="universe").first()
    assert checkpoint is not None


def test_resumes_from_checkpoint(db, xml_corpus):
    """If checkpoint exists, files up to and including that path are skipped."""
    files = sorted(xml_corpus.rglob("*.xml"))
    checkpoint = models.IngestCheckpoint(pipeline="universe", last_processed=str(files[0]))
    db.add(checkpoint)
    db.commit()

    dl = UniverseDL(db=db, corpus_dir=xml_corpus, batch_size=10)
    stats = dl.run()
    assert stats["processed"] == 1
