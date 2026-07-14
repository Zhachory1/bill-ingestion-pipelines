"""Batch embedding pipeline: encode bill text with SentenceTransformer and write to DB."""

import httpx
from loguru import logger
from sentence_transformers import SentenceTransformer
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from app.api.bills import fetch_cached_bill_text
from app.config import settings
from app.db import models


class EmbeddingPipeline:
    """Batch-encode bill metadata and full-text chunks with SentenceTransformer."""

    def __init__(
        self,
        db: Session,
        model_name: str | None = None,
        batch_size: int = 64,
        chunk_size: int = 1200,
        chunk_overlap: int = 200,
    ):
        self.db = db
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self.batch_size = batch_size
        self.chunk_size = chunk_size
        self.chunk_overlap = min(chunk_overlap, chunk_size - 1)
        self._model: SentenceTransformer | None = None

    def _load_model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info(f"Loading SentenceTransformer model: {self.model_name!r}")
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def _get_metadata_text(self, bill: models.Bill) -> str:
        parts = [bill.title or "", bill.summary or ""]
        text = " ".join(p for p in parts if p).strip()
        return text or bill.bill_id

    def _chunk_text(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return []

        chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            if end < len(text):
                boundary = text.rfind("\n\n", start, end)
                if boundary <= start + self.chunk_size // 2:
                    boundary = text.rfind(". ", start, end)
                if boundary > start:
                    end = boundary + 1

            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end >= len(text):
                break
            start = max(end - self.chunk_overlap, start + 1)
        return chunks

    def _build_bill_query(self, skipped_chunk_bill_ids: set[str]):
        no_chunks = and_(
            models.Bill.text_url.isnot(None),
            models.Bill.text_url != "",
            ~models.Bill.text_chunks.any(),
        )
        if skipped_chunk_bill_ids:
            no_chunks = and_(no_chunks, models.Bill.bill_id.notin_(skipped_chunk_bill_ids))

        return (
            self.db.query(models.Bill)
            .filter(
                or_(
                    models.Bill.embedding.is_(None),
                    no_chunks,
                    models.Bill.text_chunks.any(models.BillTextChunk.embedding.is_(None)),
                )
            )
            .order_by(models.Bill.bill_id)
            .limit(self.batch_size)
        )

    @staticmethod
    def _embedding_to_list(embedding) -> list[float]:
        return embedding.tolist() if hasattr(embedding, "tolist") else list(embedding)

    def run(self) -> dict:
        model = self._load_model()
        stats = {"embedded": 0, "chunks_embedded": 0, "full_text_fetch_failures": 0}
        skipped_chunk_bill_ids: set[str] = set()

        while True:
            bills = self._build_bill_query(skipped_chunk_bill_ids).all()
            if not bills:
                if stats["embedded"] == 0 and stats["chunks_embedded"] == 0:
                    logger.info("No bills require embedding — all up to date")
                break

            jobs = []
            for bill in bills:
                if bill.embedding is None:
                    jobs.append(("bill", bill, self._get_metadata_text(bill)))

                if bill.text_url and not bill.text_chunks:
                    try:
                        chunks = self._chunk_text(fetch_cached_bill_text(bill.text_url))
                    except httpx.HTTPError as exc:
                        logger.warning(f"Failed to fetch full text for {bill.bill_id!r}: {exc}")
                        skipped_chunk_bill_ids.add(bill.bill_id)
                        stats["full_text_fetch_failures"] += 1
                    else:
                        if not chunks:
                            skipped_chunk_bill_ids.add(bill.bill_id)
                        for index, chunk_text in enumerate(chunks):
                            bill.text_chunks.append(
                                models.BillTextChunk(
                                    chunk_index=index,
                                    text=chunk_text,
                                    source_url=bill.text_url,
                                )
                            )

                for chunk in bill.text_chunks:
                    if chunk.embedding is None:
                        jobs.append(("chunk", chunk, chunk.text))

            for offset in range(0, len(jobs), self.batch_size):
                batch = jobs[offset:offset + self.batch_size]
                embeddings = model.encode([job[2] for job in batch], show_progress_bar=False)
                for (kind, target, _), embedding in zip(batch, embeddings):
                    target.embedding = self._embedding_to_list(embedding)
                    if kind == "bill":
                        stats["embedded"] += 1
                    else:
                        stats["chunks_embedded"] += 1

            self.db.commit()
            logger.info(
                f"Embedded {stats['embedded']} bills and {stats['chunks_embedded']} chunks so far..."
            )

        logger.info(f"Embedding pipeline complete: {stats}")
        return stats
