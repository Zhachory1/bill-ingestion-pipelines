"""Batch embedding pipeline: encode bill text with SentenceTransformer and write to DB."""

from loguru import logger
from sentence_transformers import SentenceTransformer
from sqlalchemy.orm import Session
from app.config import settings
from app.db import models


class EmbeddingPipeline:
    """Batch-encode bills with SentenceTransformer, writing vectors to bills.embedding.

    Model is lazy-loaded on first run() call to avoid eager 90 MB load at construction time.
    """

    def __init__(self, db: Session, model_name: str | None = None, batch_size: int = 64):
        self.db = db
        self.model_name = model_name or settings.EMBEDDING_MODEL
        self.batch_size = batch_size
        self._model: SentenceTransformer | None = None

    def _load_model(self) -> SentenceTransformer:
        if self._model is None:
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def _get_text(self, bill: models.Bill) -> str:
        parts = [bill.title or "", bill.summary or ""]
        text = " ".join(p for p in parts if p).strip()
        return text or bill.bill_id

    def run(self) -> dict:
        model = self._load_model()
        stats = {"embedded": 0}
        while True:
            bills = (
                self.db.query(models.Bill)
                .filter(models.Bill.embedding.is_(None))
                .order_by(models.Bill.bill_id)
                .limit(self.batch_size)
                .all()
            )
            if not bills:
                break
            texts = [self._get_text(b) for b in bills]
            embeddings = model.encode(texts, show_progress_bar=False)
            for bill, emb in zip(bills, embeddings):
                bill.embedding = emb.tolist()
                stats["embedded"] += 1
            self.db.commit()
            logger.info(f"Embedded {stats['embedded']} bills so far...")
        logger.info(f"Embedding pipeline complete: {stats}")
        return stats
