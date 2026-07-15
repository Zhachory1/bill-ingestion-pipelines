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

    def _current_head(self) -> str:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()

    def _checkpoint(self) -> models.IngestCheckpoint | None:
        return self.db.query(models.IngestCheckpoint).filter_by(pipeline=self.CHECKPOINT_PIPELINE).first()

    def _set_checkpoint(self, commit_sha: str) -> None:
        checkpoint = self._checkpoint()
        if checkpoint is None:
            self.db.add(models.IngestCheckpoint(pipeline=self.CHECKPOINT_PIPELINE, last_processed=commit_sha))
        else:
            checkpoint.last_processed = commit_sha
        self.db.commit()

    def _list_all_xml_files(self) -> list[DiffEntry]:
        result = subprocess.run(
            ["git", "ls-files", "*.xml"],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return [
            DiffEntry(status="A", path=Path(line))
            for line in result.stdout.splitlines()
            if line and Path(line).suffix == ".xml"
        ]

    def _get_changed_files(self, base_ref: str | None = None) -> list[DiffEntry]:
        """Find XML files changed since the stored daily checkpoint."""
        if not base_ref:
            checkpoint = self._checkpoint()
            base_ref = checkpoint.last_processed if checkpoint else None
        if not base_ref:
            return self._list_all_xml_files()
        try:
            result = subprocess.run(
                ["git", "diff", "--name-status", base_ref, "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            logger.warning(f"Daily DL checkpoint {base_ref!r} is invalid; processing all XML files")
            return self._list_all_xml_files()
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
        head = self._current_head()
        entries = self._get_changed_files()
        logger.info(f"Found {len(entries)} changed XML files.")
        stats = self._process_entries(entries)
        if stats["failed"] == 0:
            self._set_checkpoint(head)
        logger.info(f"Daily DL complete: {stats}")
        return stats
