import shutil
import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.db import models  # noqa
from app.ingestion.daily_dl import DailyDL, DiffEntry

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_parses_git_diff_output():
    raw = "A\tdata/bills/118/hr/1/fdsys_billstatus.xml\nM\tdata/bills/118/s/5/fdsys_billstatus.xml\nD\tdata/bills/old/file.xml"
    entries = DailyDL._parse_diff_output(raw)
    assert len(entries) == 2  # D (deleted) is ignored
    assert entries[0] == DiffEntry(status="A", path=Path("data/bills/118/hr/1/fdsys_billstatus.xml"))
    assert entries[1] == DiffEntry(status="M", path=Path("data/bills/118/s/5/fdsys_billstatus.xml"))


def test_only_processes_xml_files():
    raw = "A\tdata/bills/118/hr/1/fdsys_billstatus.xml\nM\tdata/bills/118/hr/2/README.md"
    entries = DailyDL._parse_diff_output(raw)
    assert len(entries) == 1  # README.md filtered out


def test_insert_on_added(db, tmp_path):
    bill_path = tmp_path / "fdsys_billstatus.xml"
    shutil.copy(FIXTURE_DIR / "sample_billstatus.xml", bill_path)

    entries = [DiffEntry(status="A", path=bill_path)]
    dl = DailyDL(db=db, repo_path=tmp_path)
    stats = dl._process_entries(entries)

    assert stats["inserted"] == 1
    assert db.query(models.Bill).count() == 1


def test_update_on_modified(db, tmp_path):
    bill_path = tmp_path / "fdsys_billstatus.xml"
    shutil.copy(FIXTURE_DIR / "sample_billstatus.xml", bill_path)

    # Insert first so there's something to update
    entries = [DiffEntry(status="A", path=bill_path)]
    dl = DailyDL(db=db, repo_path=tmp_path)
    dl._process_entries(entries)

    entries = [DiffEntry(status="M", path=bill_path)]
    stats = dl._process_entries(entries)
    assert stats["updated"] == 1


def test_failed_parse_goes_to_dead_letter(db, tmp_path):
    bad_xml = tmp_path / "bad.xml"
    bad_xml.write_text("<billStatus><bill></bill></billStatus>")

    entries = [DiffEntry(status="A", path=bad_xml)]
    dl = DailyDL(db=db, repo_path=tmp_path)
    dl._process_entries(entries)

    assert db.query(models.ParseFailure).count() == 1
