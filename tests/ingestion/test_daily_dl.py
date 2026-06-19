import shutil
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
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


def test_first_run_no_checkpoint(db, tmp_path):
    """First run with no checkpoint should use empty tree as base."""
    dl = DailyDL(db=db, repo_path=tmp_path)
    
    # No checkpoint exists
    assert dl._get_last_checkpoint() is None
    
    # Mock git commands
    with patch("app.ingestion.daily_dl.subprocess.run") as mock_run:
        # Mock git diff output
        mock_diff = MagicMock()
        mock_diff.stdout = "A\tdata/bills/118/hr/1/fdsys_billstatus.xml"
        mock_run.return_value = mock_diff
        
        entries = dl._get_changed_files()
        
        # Should use empty tree SHA for first run
        call_args = mock_run.call_args[0][0]
        assert "4b825dc642cb6eb9a060e54bf8d69288fbee4904" in call_args
        assert "HEAD" in call_args


def test_incremental_run_uses_checkpoint(db, tmp_path):
    """Subsequent runs should use stored checkpoint commit."""
    # Create a checkpoint
    checkpoint = models.IngestCheckpoint(
        pipeline="daily",
        last_processed="abc123def456"
    )
    db.add(checkpoint)
    db.commit()
    
    dl = DailyDL(db=db, repo_path=tmp_path)
    
    # Should retrieve the checkpoint
    assert dl._get_last_checkpoint() == "abc123def456"
    
    # Mock git commands
    with patch("app.ingestion.daily_dl.subprocess.run") as mock_run:
        mock_diff = MagicMock()
        mock_diff.stdout = "M\tdata/bills/118/hr/1/fdsys_billstatus.xml"
        mock_run.return_value = mock_diff
        
        entries = dl._get_changed_files()
        
        # Should use checkpoint SHA as base
        call_args = mock_run.call_args[0][0]
        assert "abc123def456" in call_args
        assert "HEAD" in call_args


def test_checkpoint_updated_after_success(db, tmp_path):
    """Checkpoint should be updated after successful processing."""
    # Create initial checkpoint
    checkpoint = models.IngestCheckpoint(
        pipeline="daily",
        last_processed="old_commit"
    )
    db.add(checkpoint)
    db.commit()
    
    bill_path = tmp_path / "fdsys_billstatus.xml"
    shutil.copy(FIXTURE_DIR / "sample_billstatus.xml", bill_path)
    
    dl = DailyDL(db=db, repo_path=tmp_path)
    
    # Mock git commands
    with patch("app.ingestion.daily_dl.subprocess.run") as mock_run:
        def side_effect(*args, **kwargs):
            cmd = args[0]
            mock_result = MagicMock()
            if "rev-parse" in cmd:
                mock_result.stdout = "new_commit_sha"
            elif "diff" in cmd:
                mock_result.stdout = f"A\t{bill_path}"
            return mock_result
        
        mock_run.side_effect = side_effect
        
        stats = dl.run()
        
        # Checkpoint should be updated
        updated_checkpoint = db.query(models.IngestCheckpoint).filter(
            models.IngestCheckpoint.pipeline == "daily"
        ).first()
        assert updated_checkpoint.last_processed == "new_commit_sha"


def test_checkpoint_created_on_first_run(db, tmp_path):
    """Checkpoint should be created if it doesn't exist."""
    dl = DailyDL(db=db, repo_path=tmp_path)
    
    # No checkpoint initially
    assert db.query(models.IngestCheckpoint).count() == 0
    
    # Update checkpoint
    dl._update_checkpoint("first_commit_sha")
    
    # Checkpoint should now exist
    checkpoint = db.query(models.IngestCheckpoint).filter(
        models.IngestCheckpoint.pipeline == "daily"
    ).first()
    assert checkpoint is not None
    assert checkpoint.last_processed == "first_commit_sha"


def test_no_changes_returns_empty_stats(db, tmp_path):
    """If no files changed, should return empty stats without error."""
    dl = DailyDL(db=db, repo_path=tmp_path)
    
    with patch("app.ingestion.daily_dl.subprocess.run") as mock_run:
        # Mock empty diff
        mock_diff = MagicMock()
        mock_diff.stdout = ""
        
        def side_effect(*args, **kwargs):
            return mock_diff
        
        mock_run.side_effect = side_effect
        
        stats = dl.run()
        
        assert stats == {"inserted": 0, "updated": 0, "failed": 0}
