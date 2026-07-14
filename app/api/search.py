"""Semantic bill search endpoint using pgvector cosine similarity."""

import math
import re
from functools import lru_cache
from loguru import logger
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from sentence_transformers import SentenceTransformer
from app.api.deps import get_db
from app.api.schemas import SearchResponse, BillSummaryOut
from app.config import settings
from app.db import models

router = APIRouter()

_SNIPPET_CHARS = 500


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    """Return the shared SentenceTransformer instance (loaded once, thread-safe via lru_cache)."""
    return SentenceTransformer(settings.EMBEDDING_MODEL)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _snippet(text_value: str | None) -> str | None:
    if not text_value:
        return None
    value = re.sub(r"\s+", " ", text_value).strip()
    return value[:_SNIPPET_CHARS] or None


def _metadata_snippet(bill: models.Bill) -> str | None:
    return _snippet(" ".join(part for part in (bill.title, bill.summary) if part))


def _best_bill_matches(rows: list[dict], *, limit: int) -> list[dict]:
    best: dict[str, dict] = {}
    for row in rows:
        current = best.get(row["bill_id"])
        if current is None or row["score"] > current["score"]:
            best[row["bill_id"]] = row
    return sorted(best.values(), key=lambda row: row["score"], reverse=True)[:limit]


def _sqlite_vector_search(db: Session, query_vec: list[float], *, limit: int) -> list[dict]:
    rows: list[dict] = []
    for bill in db.query(models.Bill).filter(models.Bill.embedding.isnot(None)).all():
        rows.append(
            {
                "bill_id": bill.bill_id,
                "score": _cosine_similarity(query_vec, bill.embedding),
                "match_source": "title_summary",
                "snippet": _metadata_snippet(bill),
            }
        )

    for chunk in db.query(models.BillTextChunk).filter(models.BillTextChunk.embedding.isnot(None)).all():
        rows.append(
            {
                "bill_id": chunk.bill_id,
                "score": _cosine_similarity(query_vec, chunk.embedding),
                "match_source": "full_text",
                "snippet": _snippet(chunk.text),
            }
        )

    return _best_bill_matches(rows, limit=limit)


def _vector_search(db: Session, query_vec: list[float], *, limit: int) -> list[dict]:
    """Cosine similarity search across bill metadata and full-text chunk embeddings."""
    bind = db.get_bind()
    dialect = bind.dialect.name if bind is not None else "unknown"
    if dialect != "postgresql":
        return _sqlite_vector_search(db, query_vec, limit=limit)

    rows = db.execute(
        text(
            """
            WITH metadata_matches AS (
                SELECT
                    bill_id,
                    1 - (embedding <=> CAST(:vec AS vector)) AS score,
                    'title_summary' AS match_source,
                    LEFT(regexp_replace(
                        CONCAT_WS(' ', title, summary), '[[:space:]]+', ' ', 'g'
                    ), :snippet_chars) AS snippet
                FROM bills
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:vec AS vector)
                LIMIT :candidate_limit
            ), chunk_scores AS (
                SELECT
                    bill_id,
                    1 - (embedding <=> CAST(:vec AS vector)) AS score,
                    'full_text' AS match_source,
                    LEFT(regexp_replace(text, '[[:space:]]+', ' ', 'g'), :snippet_chars) AS snippet,
                    ROW_NUMBER() OVER (
                        PARTITION BY bill_id
                        ORDER BY embedding <=> CAST(:vec AS vector)
                    ) AS chunk_rank
                FROM bill_text_chunks
                WHERE embedding IS NOT NULL
            ), chunk_matches AS (
                SELECT bill_id, score, match_source, snippet
                FROM chunk_scores
                WHERE chunk_rank = 1
                ORDER BY score DESC
                LIMIT :candidate_limit
            ), matches AS (
                SELECT * FROM metadata_matches
                UNION ALL
                SELECT * FROM chunk_matches
            ), best_per_bill AS (
                SELECT DISTINCT ON (bill_id)
                    bill_id,
                    score,
                    match_source,
                    NULLIF(snippet, '') AS snippet
                FROM matches
                ORDER BY bill_id, score DESC
            )
            SELECT bill_id, score, match_source, snippet
            FROM best_per_bill
            ORDER BY score DESC
            LIMIT :limit
            """
        ),
        {
            "vec": str(query_vec),
            "limit": limit,
            "snippet_chars": _SNIPPET_CHARS,
            "candidate_limit": max(limit * 10, 50),
        },
    ).fetchall()
    return [
        {
            "bill_id": row.bill_id,
            "score": float(row.score),
            "match_source": row.match_source,
            "snippet": row.snippet,
        }
        for row in rows
    ]


def _hydrate_results(db: Session, search_rows: list[dict]) -> list[BillSummaryOut]:
    """Fetch bill rows by ID and merge with similarity scores.

    Iterates original bill_ids order (similarity rank) — IN (...) query does
    not guarantee order, so we re-apply it here via the list comprehension.
    """
    bill_ids = [r["bill_id"] for r in search_rows]
    row_map = {r["bill_id"]: r for r in search_rows}
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
            score=row_map[bid]["score"],
            match_source=row_map[bid].get("match_source"),
            snippet=row_map[bid].get("snippet"),
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
    logger.debug(f"Search query={q!r} limit={limit}")
    model = _get_model()
    query_vec = model.encode(q).tolist()
    raw = _vector_search(db, query_vec, limit=limit)
    results = _hydrate_results(db, raw)
    logger.debug(f"Search query={q!r} returned {len(results)} results")
    return SearchResponse(query=q, results=results)
