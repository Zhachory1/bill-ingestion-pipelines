"""Bill detail endpoints: metadata, sponsors/subjects, and text payload for LLM context."""

import re

import httpx
from loguru import logger
from lxml import etree  # type: ignore
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from app.api.deps import get_db
from app.api.schemas import BillOut, BillTextOut, BillFullTextOut
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
