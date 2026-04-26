from dataclasses import dataclass
from pathlib import Path
from loguru import logger
from sqlalchemy.orm import Session
from app.db import models
from app.ingestion.xml_parser import BillStatusParser
from app.ingestion.db_writer import upsert_bill


@dataclass
class UniverseDL:
    db: Session
    corpus_dir: Path
    batch_size: int = 100

    def _enumerate_xml_files(self) -> list[Path]:
        return sorted(self.corpus_dir.rglob("*.xml"))

    def _get_checkpoint(self) -> str | None:
        cp = self.db.query(models.IngestCheckpoint).filter_by(pipeline="universe").first()
        return cp.last_processed if cp else None

    def _save_checkpoint(self, last_path: str) -> None:
        cp = self.db.query(models.IngestCheckpoint).filter_by(pipeline="universe").first()
        if cp is None:
            cp = models.IngestCheckpoint(pipeline="universe")
            self.db.add(cp)
        cp.last_processed = last_path
        self.db.commit()

    def _log_failure(self, path: Path, error: Exception) -> None:
        self.db.add(models.ParseFailure(file_path=str(path), error_message=str(error)))
        self.db.commit()

    def run(self) -> dict:
        """Process all XML files in corpus_dir, resuming from checkpoint if set."""
        all_files = self._enumerate_xml_files()
        checkpoint = self._get_checkpoint()
        stats = {"processed": 0, "failed": 0, "skipped": 0}

        if checkpoint:
            try:
                checkpoint_idx = [str(f) for f in all_files].index(checkpoint)
                all_files = all_files[checkpoint_idx + 1:]
                stats["skipped"] = checkpoint_idx + 1
                logger.info(f"Resuming from checkpoint; skipping {stats['skipped']} files.")
            except ValueError:
                logger.warning("Checkpoint path not found in corpus; starting from beginning.")

        batch: list[Path] = []
        for xml_file in all_files:
            batch.append(xml_file)
            if len(batch) >= self.batch_size:
                self._process_batch(batch, stats)
                batch = []

        if batch:
            self._process_batch(batch, stats)

        logger.info(f"Universe DL complete: {stats}")
        return stats

    def _process_batch(self, batch: list[Path], stats: dict) -> None:
        for xml_file in batch:
            try:
                parsed = BillStatusParser.parse(xml_file)
                upsert_bill(self.db, parsed)
                self.db.commit()
                stats["processed"] += 1
                logger.debug(f"Upserted {parsed.bill_id}")
            except Exception as e:
                self.db.rollback()
                self._log_failure(xml_file, e)
                stats["failed"] += 1
                logger.warning(f"Failed to parse {xml_file}: {e}")
        if batch:
            self._save_checkpoint(str(batch[-1]))
