"""Incremental ingestion pipeline using git diff to find newly changed bills."""

from dataclasses import dataclass
from pathlib import Path
import subprocess
from loguru import logger
from sqlalchemy.orm import Session
from app.db import models
from app.ingestion.xml_parser import BillStatusParser
from app.ingestion.db_writer import upsert_bill


@dataclass(frozen=True)
class DiffEntry:
    status: str   # "A" or "M"
    path: Path


class DailyDL:
    CHECKPOINT_PIPELINE = "daily"

    def __init__(self, db: Session, repo_path: Path):
        self.db = db
        self.repo_path = repo_path

    @staticmethod
    def _parse_diff_output(raw: str) -> list[DiffEntry]:
        """Parse `git diff --name-status` output into DiffEntry list.

        Ignores deletions (D) and non-XML files.
        """
        entries = []
        for line in raw.strip().splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            status, path_str = parts
            if status not in ("A", "M"):
                continue
            path = Path(path_str)
            if path.suffix != ".xml":
                continue
            entries.append(DiffEntry(status=status, path=path))
        return entries

    def _get_last_checkpoint(self) -> str | None:
        """Retrieve last processed commit SHA from checkpoint table."""
        checkpoint = (
            self.db.query(models.IngestCheckpoint)
            .filter(models.IngestCheckpoint.pipeline == self.CHECKPOINT_PIPELINE)
            .first()
        )
        return checkpoint.last_processed if checkpoint else None

    def _get_current_commit(self) -> str:
        """Get current HEAD commit SHA."""
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def _update_checkpoint(self, commit_sha: str) -> None:
        """Update checkpoint with successfully processed commit SHA."""
        checkpoint = (
            self.db.query(models.IngestCheckpoint)
            .filter(models.IngestCheckpoint.pipeline == self.CHECKPOINT_PIPELINE)
            .first()
        )
        if checkpoint:
            checkpoint.last_processed = commit_sha
        else:
            checkpoint = models.IngestCheckpoint(
                pipeline=self.CHECKPOINT_PIPELINE,
                last_processed=commit_sha,
            )
            self.db.add(checkpoint)
        self.db.commit()

    def _get_changed_files(self) -> list[DiffEntry]:
        """Run git diff to find files changed since last checkpoint.
        
        Uses stored checkpoint commit SHA if available, otherwise compares
        against first commit (full history) for initial run.
        """
        last_commit = self._get_last_checkpoint()
        
        if last_commit:
            # Incremental: diff from last checkpoint to HEAD
            base_ref = last_commit
            logger.info(f"Comparing {last_commit[:8]} -> HEAD")
        else:
            # First run: get all files (use empty tree SHA)
            base_ref = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git empty tree
            logger.info("First run: processing all files")
        
        result = subprocess.run(
            ["git", "diff", "--name-status", base_ref, "HEAD"],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return self._parse_diff_output(result.stdout)

    def _process_entries(self, entries: list[DiffEntry]) -> dict:
        stats = {"inserted": 0, "updated": 0, "failed": 0}
        for entry in entries:
            path = entry.path if entry.path.is_absolute() else self.repo_path / entry.path
            try:
                parsed = BillStatusParser.parse(path)
                existing = self.db.get(models.Bill, parsed.bill_id)
                upsert_bill(self.db, parsed)
                self.db.commit()
                if existing is None:
                    stats["inserted"] += 1
                else:
                    stats["updated"] += 1
                logger.debug(f"{'Inserted' if existing is None else 'Updated'} {parsed.bill_id}")
            except Exception as e:
                self.db.rollback()
                self.db.add(models.ParseFailure(file_path=str(path), error_message=str(e)))
                self.db.commit()
                stats["failed"] += 1
                logger.warning(f"Failed to process {path}: {e}")
        return stats

    def run(self) -> dict:
        """Pull updates and process git diff."""
        logger.info("Daily DL: fetching changed files from git diff...")
        entries = self._get_changed_files()
        logger.info(f"Found {len(entries)} changed XML files.")
        
        if not entries:
            logger.info("No changes to process")
            return {"inserted": 0, "updated": 0, "failed": 0}
        
        stats = self._process_entries(entries)
        
        # Update checkpoint only after successful processing
        current_commit = self._get_current_commit()
        self._update_checkpoint(current_commit)
        logger.info(f"Updated checkpoint to {current_commit[:8]}")
        
        logger.info(f"Daily DL complete: {stats}")
        return stats
