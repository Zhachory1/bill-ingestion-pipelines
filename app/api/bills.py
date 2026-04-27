"""Bill detail endpoints: metadata, sponsors/subjects, and text payload for LLM context."""

import math
import re

import httpx
from loguru import logger
from lxml import etree  # type: ignore
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session, joinedload
from app.api.deps import get_db
from app.api.schemas import BillOut, BillTextOut, BillFullTextOut, BillSummaryOut
from app.api.search import _hydrate_results
from app.db import models


def _html_url_from_xml_url(xml_url: str) -> str:
    """Derive the govinfo HTML URL from the stored XML URL.

    e.g. .../xml/BILLS-118hr1ih.xml  →  .../html/BILLS-118hr1ih.htm
    """
    return xml_url.replace("/xml/", "/html/").replace(".xml", ".htm")


def fetch_bill_text(xml_url: str) -> str:
    """Fetch the govinfo HTML version of a bill and return plain text.

    Falls back to the XML URL if the HTML URL returns an error.
    Raises httpx.HTTPError on both-fail.
    """
    html_url = _html_url_from_xml_url(xml_url)
    for url in (html_url, xml_url):
        try:
            resp = httpx.get(url, timeout=15, follow_redirects=True)
            resp.raise_for_status()
        except httpx.HTTPError:
            continue

        if "html" in url:
            # govinfo HTML is plain text wrapped in <pre> — extract that text node
            try:
                root = etree.fromstring(resp.content, etree.HTMLParser())
                pre = root.find(".//pre")
                text = "".join(pre.itertext()) if pre is not None else "".join(root.itertext())
            except Exception:
                text = re.sub(r'<[^>]+>', ' ', resp.text)
        else:
            try:
                root = etree.fromstring(resp.content)
                text = " ".join(root.itertext())
            except etree.XMLSyntaxError:
                text = resp.text

        # Collapse horizontal whitespace runs but preserve newlines
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    raise httpx.HTTPError(f"Both HTML and XML fetch failed for {xml_url}")

router = APIRouter()


def _get_bill_or_404(db: Session, bill_id: str) -> models.Bill:
    """Fetch a bill with its subjects/sponsors eager-loaded, or raise HTTP 404."""
    bill = (
        db.query(models.Bill)
        .options(
            joinedload(models.Bill.subjects),
            joinedload(models.Bill.sponsors),
            joinedload(models.Bill.cosponsors),
        )
        .filter(models.Bill.bill_id == bill_id)
        .first()
    )
    if bill is None:
        logger.warning(f"Bill not found: {bill_id!r}")
        raise HTTPException(status_code=404, detail=f"Bill {bill_id!r} not found")
    return bill


@router.get("/bills/{bill_id}", response_model=BillOut)
def get_bill(bill_id: str, db: Session = Depends(get_db)):
    """Return full bill metadata including subjects and sponsors."""
    # from_orm_bill is required (rather than returning the ORM object directly)
    # because subjects need explicit name extraction: [s.name for s in bill.subjects].
    return BillOut.from_orm_bill(_get_bill_or_404(db, bill_id))


@router.get("/bills/{bill_id}/text", response_model=BillTextOut)
def get_bill_text(bill_id: str, db: Session = Depends(get_db)):
    """Return the bill's title + summary as a single text blob for LLM context.

    Falls back to bill_id when both title and summary are absent.
    """
    bill = _get_bill_or_404(db, bill_id)
    parts = [bill.title or "", bill.summary or ""]
    text = "\n\n".join(p for p in parts if p).strip() or bill_id
    return BillTextOut(bill_id=bill.bill_id, title=bill.title, text=text)


@router.get("/bills/{bill_id}/fulltext", response_model=BillFullTextOut)
def get_bill_fulltext(bill_id: str, db: Session = Depends(get_db)):
    """Fetch full legislative text from govinfo.gov and return as plain text.

    Fetches XML on demand — text is never stored server-side.
    Returns 404 if no text URL exists, 502 if govinfo fetch fails.
    """
    bill = _get_bill_or_404(db, bill_id)
    if not bill.text_url:
        raise HTTPException(status_code=404, detail="No full text available for this bill")

    html_url = _html_url_from_xml_url(bill.text_url)
    logger.info(f"Fetching full text for {bill_id!r} from {html_url}")
    try:
        text = fetch_bill_text(bill.text_url)
    except httpx.HTTPError as e:
        logger.warning(f"govinfo fetch failed for {bill_id!r}: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch bill text from govinfo.gov")

    return BillFullTextOut(bill_id=bill_id, text_url=html_url, text=text)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity for SQLite fallback."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


@router.get("/bills/{bill_id}/similar", response_model=list[BillSummaryOut])
def get_similar_bills(
    bill_id: str,
    # Cap at 10 (intentionally lower than search's 100) — this is a UI widget, not a bulk API
    limit: int = Query(10, ge=1, le=10),
    db: Session = Depends(get_db),
):
    """Return up to 10 bills most similar to the given bill using pgvector cosine similarity.

    Requires the bill to have an embedding; returns 404 if not.
    The source bill is excluded from results.
    Uses pgvector on PostgreSQL; falls back to Python cosine similarity on SQLite (tests).
    """
    bill = _get_bill_or_404(db, bill_id)
    if bill.embedding is None:
        raise HTTPException(status_code=404, detail="No embedding available for this bill")

    bind = db.get_bind()
    dialect = bind.dialect.name if bind is not None else "unknown"

    if dialect == "postgresql":
        rows = db.execute(
            text(
                "SELECT bill_id, 1 - (embedding <=> CAST(:vec AS vector)) AS score "
                "FROM bills WHERE embedding IS NOT NULL AND bill_id != :bill_id "
                "ORDER BY embedding <=> CAST(:vec AS vector) "
                "LIMIT :limit"
            ),
            {"vec": str(list(bill.embedding)), "limit": limit, "bill_id": bill_id},
        ).fetchall()
        search_rows = [{"bill_id": row.bill_id, "score": float(row.score)} for row in rows]
    else:
        # SQLite fallback: load all embeddings and rank in Python
        candidates = (
            db.query(models.Bill)
            .filter(models.Bill.bill_id != bill_id, models.Bill.embedding.isnot(None))
            .all()
        )
        scored = [
            {"bill_id": c.bill_id, "score": _cosine_similarity(bill.embedding, c.embedding)}
            for c in candidates
        ]
        scored.sort(key=lambda r: r["score"], reverse=True)
        search_rows = scored[:limit]

    return _hydrate_results(db, search_rows)
