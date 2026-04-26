from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from sentence_transformers import SentenceTransformer
from app.api.deps import get_db
from app.api.schemas import SearchResponse, BillSummaryOut
from app.config import settings

router = APIRouter()

_model_instance: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model_instance
    if _model_instance is None:
        _model_instance = SentenceTransformer(settings.EMBEDDING_MODEL)
    return _model_instance


def _vector_search(db: Session, query_vec: list[float], *, limit: int) -> list[dict]:
    """Cosine similarity search via pgvector. Returns [{bill_id, score}].

    str(query_vec) produces '[0.1, 0.2, ...]' — pgvector accepts this format
    for CAST(:vec AS vector).
    """
    rows = db.execute(
        text(
            "SELECT bill_id, 1 - (embedding <=> CAST(:vec AS vector)) AS score "
            "FROM bills WHERE embedding IS NOT NULL "
            "ORDER BY embedding <=> CAST(:vec AS vector) "
            "LIMIT :limit"
        ),
        {"vec": str(query_vec), "limit": limit},
    ).fetchall()
    return [{"bill_id": row.bill_id, "score": float(row.score)} for row in rows]


def _hydrate_results(db: Session, search_rows: list[dict]) -> list[BillSummaryOut]:
    """Fetch bill rows by ID and merge with similarity scores.

    Iterates original bill_ids order (similarity rank) — IN (...) query does
    not guarantee order, so we re-apply it here via the list comprehension.
    """
    from app.db import models
    bill_ids = [r["bill_id"] for r in search_rows]
    scores = {r["bill_id"]: r["score"] for r in search_rows}
    bills = db.query(models.Bill).filter(models.Bill.bill_id.in_(bill_ids)).all()
    bill_map = {b.bill_id: b for b in bills}
    return [
        BillSummaryOut(
            bill_id=bid,
            title=bill_map[bid].title,
            summary=bill_map[bid].summary,
            chamber=bill_map[bid].chamber,
            introduced_date=bill_map[bid].introduced_date,
            bill_url=bill_map[bid].bill_url,
            score=scores[bid],
        )
        for bid in bill_ids
        if bid in bill_map
    ]


@router.get("/search", response_model=SearchResponse)
def search_bills(
    q: str = Query(..., min_length=1, description="Natural-language search query"),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    model = _get_model()
    query_vec = model.encode(q).tolist()
    raw = _vector_search(db, query_vec, limit=limit)
    results = _hydrate_results(db, raw)
    return SearchResponse(query=q, results=results)
