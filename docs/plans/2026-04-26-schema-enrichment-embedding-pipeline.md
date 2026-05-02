# Schema Enrichment + Embedding Pipeline Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich the Bill schema with missing fields (`introduced_date`, `chamber`, `bill_url`, legislative subjects), update the XML parser to extract them, and build an embedding pipeline that populates `bills.embedding` using `sentence-transformers`.

**Architecture:** Extend `app/db/models.py` with three new columns on `Bill` and a `LegislativeSubject` + `bill_subjects` join table. Update `ParsedBill` and `BillStatusParser` to extract these fields. Add `app/ingestion/embedding_pipeline.py` that queries `bills WHERE embedding IS NULL` in batches, encodes `title + summary` text with `SentenceTransformer`, and writes vectors back. Wire it into `app/cli.py` as `embed-bills`. Finishes with all bills fully populated for semantic search (Project 2 prerequisite).

**Tech Stack:** SQLAlchemy 2.x, Alembic, pgvector, lxml, sentence-transformers, Typer, pytest/SQLite in-memory for tests.

**Depends on:** `feature/bill-ingestion-pipelines` (Universe DL, Daily DL, initial schema with `embedding` column already added).
**Required by:** `2026-04-26-search-bill-data-api.md` (pgvector search needs populated embeddings and subjects).

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `app/db/models.py` | Modify | Add `introduced_date`, `chamber`, `bill_url` to `Bill`; add `LegislativeSubject` model and `bill_subjects` association table |
| `app/ingestion/xml_parser.py` | Modify | Extract `introducedDate`, derive `chamber` from `billType`, construct `bill_url`, extract legislative subjects |
| `app/ingestion/db_writer.py` | Modify | Upsert `LegislativeSubject` rows and `bill_subjects` links |
| `app/ingestion/embedding_pipeline.py` | Create | Batch-encode bills with `SentenceTransformer`; write vectors to `bills.embedding` |
| `app/cli.py` | Modify | Add `embed-bills` Typer command |
| `alembic/versions/<hash>_enrich_bill_schema.py` | Create | Add new columns + subjects tables via Alembic |
| `tests/test_models.py` | Modify | Add tests for new columns and subjects relationship |
| `tests/ingestion/test_xml_parser.py` | Modify | Add tests for new extracted fields |
| `tests/ingestion/test_db_writer.py` | Modify | Add tests for subject upsert and linking |
| `tests/ingestion/test_embedding_pipeline.py` | Create | Tests for embedding pipeline (mock SentenceTransformer) |
| `tests/ingestion/fixtures/sample_billstatus.xml` | Modify | Add `<introducedDate>` and `<subjects>` elements |

---

## Task 1: Schema — New Bill Fields + Subjects Table

**Files:**
- Modify: `app/db/models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_models.py`:

```python
def test_bill_new_fields(db):
    bill = models.Bill(
        bill_id="118-hr-99", congress=118, bill_type="hr", bill_number=99,
        title="Test", latest_action="", latest_action_date="2023-01-01",
        last_updated="2023-01-01",
        introduced_date="2023-01-05",
        chamber="House",
        bill_url="https://www.congress.gov/bill/118th-congress/house-bill/99",
    )
    db.add(bill)
    db.commit()
    result = db.query(models.Bill).filter_by(bill_id="118-hr-99").one()
    assert result.introduced_date == "2023-01-05"
    assert result.chamber == "House"
    assert result.bill_url == "https://www.congress.gov/bill/118th-congress/house-bill/99"

def test_legislative_subjects(db):
    bill = models.Bill(
        bill_id="118-hr-55", congress=118, bill_type="hr", bill_number=55,
        title="Health Bill", latest_action="", latest_action_date="2023-01-01",
        last_updated="2023-01-01",
    )
    subject = models.LegislativeSubject(name="Health care")
    bill.subjects.append(subject)
    db.add(bill)
    db.commit()
    result = db.query(models.Bill).filter_by(bill_id="118-hr-55").one()
    assert len(result.subjects) == 1
    assert result.subjects[0].name == "Health care"

def test_subject_unique_constraint_enforced(db):
    """Unique constraint on name must reject raw duplicate inserts."""
    from sqlalchemy.exc import IntegrityError
    db.add(models.LegislativeSubject(name="Taxation"))
    db.commit()
    db.add(models.LegislativeSubject(name="Taxation"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_models.py::test_bill_new_fields tests/test_models.py::test_legislative_subjects tests/test_models.py::test_subject_unique_constraint_enforced -v
```

Expected: `AttributeError: type object 'Bill' has no attribute 'introduced_date'`

- [ ] **Step 3: Add fields and models to `app/db/models.py`**

Add after existing imports:
```python
from sqlalchemy import UniqueConstraint
```

Add association table (after `bill_cosponsors`):
```python
bill_subjects = Table(
    "bill_subjects", Base.metadata,
    Column("bill_id", String, ForeignKey("bills.bill_id"), primary_key=True),
    Column("subject_id", Integer, ForeignKey("legislative_subjects.id"), primary_key=True),
)
```

Add new columns to `Bill` (after `last_updated`):
```python
introduced_date: Mapped[str | None] = mapped_column(String(20), nullable=True)  # String(20) mirrors latest_action_date pattern
chamber: Mapped[str | None] = mapped_column(String(10), nullable=True)   # "House" or "Senate"
bill_url: Mapped[str | None] = mapped_column(Text, nullable=True)

subjects: Mapped[list["LegislativeSubject"]] = relationship(
    "LegislativeSubject", secondary=bill_subjects, back_populates="bills"
)
```

Add new model (after `IngestCheckpoint`):
```python
class LegislativeSubject(Base):
    __tablename__ = "legislative_subjects"
    __table_args__ = (UniqueConstraint("name", name="uq_subject_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    bills: Mapped[list["Bill"]] = relationship(
        "Bill", secondary=bill_subjects, back_populates="subjects"
    )
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest tests/test_models.py -v
```

Expected: all tests including 3 new ones PASS. Note: `test_subject_unique_constraint_enforced` requires the `unique=True` on `LegislativeSubject.name` — the SQLite in-memory DB will enforce this.

- [ ] **Step 5: Commit**

```bash
git add app/db/models.py tests/test_models.py
git commit -m "feat: add introduced_date, chamber, bill_url, and legislative subjects to Bill schema"
```

---

## Task 2: Alembic Migration

**Files:**
- Create: `alembic/versions/<hash>_enrich_bill_schema.py`

No tests for migrations (Alembic runs against a live DB; the model tests cover schema correctness via SQLite).

- [ ] **Step 1: Generate migration**

Postgres must be running (`docker compose up -d postgres`) and `.env` must have `DATABASE_URL` pointing to it.

```bash
uv run alembic revision --autogenerate -m "enrich bill schema with chamber, introduced_date, bill_url, and subjects"
```

- [ ] **Step 2: Inspect the generated file**

Open the generated `alembic/versions/<hash>_enrich_bill_schema.py`. Verify it contains:
- `op.add_column('bills', sa.Column('introduced_date', ...))` 
- `op.add_column('bills', sa.Column('chamber', ...))`
- `op.add_column('bills', sa.Column('bill_url', ...))`
- `op.create_table('legislative_subjects', ...)`
- `op.create_table('bill_subjects', ...)`

If autogenerate missed anything (can happen with association tables using `Table()`), add the missing statements manually.

- [ ] **Step 3: Apply migration**

```bash
uv run alembic upgrade head
```

Expected: `Running upgrade b2c3d4e5f6a7 -> <new_hash>, enrich bill schema ...`

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/
git commit -m "feat: migration — enrich bill schema with chamber, introduced_date, bill_url, subjects"
```

---

## Task 3: XML Parser Update

**Files:**
- Modify: `app/ingestion/xml_parser.py`
- Modify: `tests/ingestion/fixtures/sample_billstatus.xml`
- Modify: `tests/ingestion/test_xml_parser.py`

The BILLSTATUS XML provides:
- `<introducedDate>2023-01-10</introducedDate>` (direct child of `<bill>`)
- `<subjects><legislativeSubjects><item><name>Health care</name></item>...</legislativeSubjects></subjects>`
- Chamber is derived from `billType`: any type starting with `h` → `"House"`, starting with `s` → `"Senate"`
- `bill_url` constructed as: `https://www.congress.gov/bill/{congress}th-congress/{readable_type}/{bill_number}`

`readable_type` mapping:
```
hr → house-bill          s → senate-bill
hres → house-resolution  sres → senate-resolution
hjres → house-joint-resolution   sjres → senate-joint-resolution
hconres → house-concurrent-resolution  sconres → senate-concurrent-resolution
```

- [ ] **Step 1: Update the XML fixture**

Add to `tests/ingestion/fixtures/sample_billstatus.xml` inside `<bill>`:

```xml
    <introducedDate>2023-01-10</introducedDate>
    <subjects>
      <legislativeSubjects>
        <item><name>Health care</name></item>
        <item><name>Taxation</name></item>
      </legislativeSubjects>
    </subjects>
```

- [ ] **Step 2: Write failing tests**

Add to `tests/ingestion/test_xml_parser.py`:

```python
def test_parses_introduced_date():
    result = BillStatusParser.parse(FIXTURE)
    assert result.introduced_date == "2023-01-10"

def test_parses_chamber_house():
    result = BillStatusParser.parse(FIXTURE)  # billType=HR → House
    assert result.chamber == "House"

def test_parses_bill_url():
    result = BillStatusParser.parse(FIXTURE)
    assert result.bill_url == "https://www.congress.gov/bill/118th-congress/house-bill/1234"

def test_parses_subjects():
    result = BillStatusParser.parse(FIXTURE)
    assert sorted(result.subjects) == ["Health care", "Taxation"]

def test_chamber_senate(tmp_path):
    senate_xml = tmp_path / "senate.xml"
    senate_xml.write_text("""<?xml version="1.0" encoding="UTF-8"?>
<billStatus><bill>
  <billType>S</billType><billNumber>5</billNumber><congress>118</congress>
  <title>A Senate Bill</title><updateDate>2023-01-01T00:00:00Z</updateDate>
  <sponsors/><cosponsors/><actions/><summaries/>
</bill></billStatus>""")
    result = BillStatusParser.parse(senate_xml)
    assert result.chamber == "Senate"
    assert result.bill_url == "https://www.congress.gov/bill/118th-congress/senate-bill/5"
```

- [ ] **Step 3: Run to confirm failure**

```bash
uv run pytest tests/ingestion/test_xml_parser.py -v -k "introduced_date or chamber or bill_url or subjects or senate"
```

Expected: `AttributeError: 'ParsedBill' object has no attribute 'introduced_date'`

- [ ] **Step 4: Update `ParsedBill` dataclass**

Add fields to `ParsedBill` in `app/ingestion/xml_parser.py`:

```python
@dataclass
class ParsedBill:
    bill_id: str
    congress: int
    bill_type: str
    bill_number: int
    title: str | None
    summary: str | None
    latest_action: str | None
    latest_action_date: str | None
    last_updated: str | None
    introduced_date: str | None = None
    chamber: str | None = None
    bill_url: str | None = None
    subjects: list[str] = field(default_factory=list)
    sponsors: list[ParsedSponsor] = field(default_factory=list)
    cosponsors: list[ParsedSponsor] = field(default_factory=list)
```

- [ ] **Step 5: Update `BillStatusParser.parse()`**

Add a `_BILL_TYPE_URL_MAP` constant at module level:

```python
_BILL_TYPE_URL_MAP = {
    "hr": "house-bill",
    "s": "senate-bill",
    "hres": "house-resolution",
    "sres": "senate-resolution",
    "hjres": "house-joint-resolution",
    "sjres": "senate-joint-resolution",
    "hconres": "house-concurrent-resolution",
    "sconres": "senate-concurrent-resolution",
}
```

In `parse()`, after deriving `bill_id`, add:

```python
introduced_date = opt("introducedDate")
chamber = "House" if bill_type.startswith("h") else "Senate" if bill_type.startswith("s") else None
readable_type = _BILL_TYPE_URL_MAP.get(bill_type, bill_type)
bill_url = f"https://www.congress.gov/bill/{congress}th-congress/{readable_type}/{bill_number}"

subjects = [
    el.text.strip()
    for el in bill.findall(".//subjects/legislativeSubjects/item/name")
    if el.text
]
```

Update the `return ParsedBill(...)` to include the new fields:

```python
return ParsedBill(
    bill_id=bill_id,
    congress=congress,
    bill_type=bill_type,
    bill_number=bill_number,
    title=opt("title"),
    summary=bill.findtext(".//summaries/summary/text"),
    latest_action=latest_action or None,
    latest_action_date=latest_action_date or None,
    last_updated=opt("updateDate"),
    introduced_date=introduced_date,
    chamber=chamber,
    bill_url=bill_url,
    subjects=subjects,
    sponsors=parse_sponsors("sponsors"),
    cosponsors=parse_sponsors("cosponsors"),
)
```

- [ ] **Step 6: Run all parser tests**

```bash
uv run pytest tests/ingestion/test_xml_parser.py -v
```

Expected: all tests PASS (existing 7 + 5 new = 12 total).

- [ ] **Step 7: Commit**

```bash
git add app/ingestion/xml_parser.py tests/ingestion/test_xml_parser.py tests/ingestion/fixtures/sample_billstatus.xml
git commit -m "feat: extract introduced_date, chamber, bill_url, and subjects from BILLSTATUS XML"
```

---

## Task 4: DB Writer — Subject Upsert

**Prerequisite:** Task 3 must be merged first — `ParsedBill` must already include `introduced_date`, `chamber`, `bill_url`, and `subjects` fields.

**Files:**
- Modify: `app/ingestion/db_writer.py`
- Modify: `tests/ingestion/test_db_writer.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/ingestion/test_db_writer.py`:

```python
def test_upsert_creates_subjects(db):
    bill = make_parsed_bill(
        subjects=["Health care", "Taxation"],
        introduced_date="2023-01-05",
        chamber="House",
        bill_url="https://www.congress.gov/bill/118th-congress/house-bill/1",
    )
    upsert_bill(db, bill)
    db.commit()
    result = db.query(models.Bill).one()
    assert len(result.subjects) == 2
    assert {s.name for s in result.subjects} == {"Health care", "Taxation"}

def test_upsert_does_not_duplicate_subjects(db):
    """Inserting the same bill twice must not create duplicate subject rows."""
    bill = make_parsed_bill(subjects=["Health care"])
    upsert_bill(db, bill)
    db.commit()
    upsert_bill(db, bill)
    db.commit()
    assert db.query(models.LegislativeSubject).count() == 1

def test_upsert_shares_subjects_across_bills(db):
    """Same subject name from two different bills → one LegislativeSubject row."""
    upsert_bill(db, make_parsed_bill(bill_id="118-hr-1", bill_number=1, subjects=["Health care"]))
    upsert_bill(db, make_parsed_bill(bill_id="118-hr-2", bill_number=2, subjects=["Health care"]))
    db.commit()
    assert db.query(models.LegislativeSubject).count() == 1
    assert db.query(models.Bill).count() == 2
```

Also update `make_parsed_bill` to accept and default new fields:

```python
def make_parsed_bill(**kwargs) -> ParsedBill:
    defaults = dict(
        bill_id="118-hr-1",
        congress=118,
        bill_type="hr",
        bill_number=1,
        title="Test Bill",
        summary="A summary",
        latest_action="Passed",
        latest_action_date="2023-01-15",
        last_updated="2023-01-15T10:00:00Z",
        introduced_date="2023-01-05",
        chamber="House",
        bill_url="https://www.congress.gov/bill/118th-congress/house-bill/1",
        subjects=[],
        sponsors=[ParsedSponsor("A000001", "Jane Doe", "D", "CA")],
        cosponsors=[],
    )
    defaults.update(kwargs)
    return ParsedBill(**defaults)
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/ingestion/test_db_writer.py -v -k "subject"
```

Expected: `TypeError: ParsedBill.__init__() got an unexpected keyword argument 'subjects'` (until parser task is merged) or `AssertionError` on subject count.

- [ ] **Step 3: Update `upsert_bill` in `app/ingestion/db_writer.py`**

Add `_upsert_subject` as a module-level helper (uses `models.LegislativeSubject`, consistent with existing `db_writer.py` style):

```python
from sqlalchemy.exc import IntegrityError

def _upsert_subject(db: Session, name: str) -> models.LegislativeSubject:
    """Return existing LegislativeSubject or create a new one.

    Uses try/except around flush so concurrent writers hitting a race between
    SELECT and INSERT don't crash — the IntegrityError is caught, the savepoint
    rolled back, and the now-existing row is re-fetched.
    """
    existing = db.query(models.LegislativeSubject).filter_by(name=name).first()
    if existing is not None:
        return existing
    try:
        obj = models.LegislativeSubject(name=name)
        db.add(obj)
        db.flush()
        return obj
    except IntegrityError:
        db.rollback()
        return db.query(models.LegislativeSubject).filter_by(name=name).one()
```

In `upsert_bill`, add after the existing sponsor relationship rebuild:

```python
bill.subjects = [_upsert_subject(db, name) for name in parsed.subjects]
```

Also update the `Bill` construction blocks to include the new fields:

```python
# In the "if existing is None" branch:
bill = models.Bill(
    ...
    introduced_date=parsed.introduced_date,
    chamber=parsed.chamber,
    bill_url=parsed.bill_url,
)
# In the "else" branch:
bill.introduced_date = parsed.introduced_date
bill.chamber = parsed.chamber
bill.bill_url = parsed.bill_url
```

- [ ] **Step 4: Run all writer tests**

```bash
uv run pytest tests/ingestion/test_db_writer.py -v
```

Expected: all tests PASS (existing 4 + 3 new = 7 total).

- [ ] **Step 5: Run full suite**

```bash
uv run pytest -v
```

Expected: all tests PASS (subjects, parser, models, integration).

- [ ] **Step 6: Commit**

```bash
git add app/ingestion/db_writer.py tests/ingestion/test_db_writer.py
git commit -m "feat: upsert legislative subjects in db_writer"
```

---

## Task 5: Embedding Pipeline

**Files:**
- Create: `app/ingestion/embedding_pipeline.py`
- Create: `tests/ingestion/test_embedding_pipeline.py`

The pipeline queries `bills WHERE embedding IS NULL` in batches. Because we commit after each batch and update `embedding`, records drop out of the filter automatically — no offset needed. `SentenceTransformer` is mocked in tests to avoid loading a 90 MB model.

- [ ] **Step 1: Write failing tests**

```python
# tests/ingestion/test_embedding_pipeline.py
import pytest
from unittest.mock import patch, MagicMock
import numpy as np
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.db import models  # noqa
from app.ingestion.embedding_pipeline import EmbeddingPipeline

FAKE_DIM = 4  # tiny for tests


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _make_bill(db, bill_id: str, title: str = "T", summary: str = "S"):
    bill = models.Bill(
        bill_id=bill_id, congress=118, bill_type="hr",
        bill_number=int(bill_id.split("-")[-1]),
        title=title, latest_action="", latest_action_date="2023-01-01",
        last_updated="2023-01-01",
    )
    db.add(bill)
    db.commit()
    return bill


@pytest.fixture
def mock_encoder():
    """Patch SentenceTransformer so tests don't load a real model."""
    with patch("app.ingestion.embedding_pipeline.SentenceTransformer") as MockST:
        instance = MockST.return_value
        instance.encode.side_effect = lambda texts, **kwargs: np.ones(
            (len(texts), FAKE_DIM), dtype=np.float32
        )
        yield instance


def test_embeds_bills_with_null_embedding(db, mock_encoder):
    _make_bill(db, "118-hr-1")
    _make_bill(db, "118-hr-2")

    pipeline = EmbeddingPipeline(db=db, batch_size=10)
    stats = pipeline.run()

    assert stats["embedded"] == 2
    assert db.query(models.Bill).filter(models.Bill.embedding.is_(None)).count() == 0


def test_skips_already_embedded_bills(db, mock_encoder):
    bill = _make_bill(db, "118-hr-1")
    bill.embedding = [0.1, 0.2, 0.3, 0.4]
    db.commit()
    _make_bill(db, "118-hr-2")  # no embedding

    pipeline = EmbeddingPipeline(db=db, batch_size=10)
    stats = pipeline.run()

    assert stats["embedded"] == 1  # only the null one


def test_batch_processing(db, mock_encoder):
    for i in range(1, 6):
        _make_bill(db, f"118-hr-{i}")

    pipeline = EmbeddingPipeline(db=db, batch_size=2)
    stats = pipeline.run()

    assert stats["embedded"] == 5
    assert mock_encoder.encode.call_count == 3  # ceil(5/2) batches


def test_text_construction_title_plus_summary(db, mock_encoder):
    _make_bill(db, "118-hr-1", title="Climate Bill", summary="Reduces emissions.")

    pipeline = EmbeddingPipeline(db=db, batch_size=10)
    pipeline.run()

    calls = mock_encoder.encode.call_args_list
    assert len(calls) == 1
    texts_passed = calls[0][0][0]  # positional arg: list of texts
    assert texts_passed[0] == "Climate Bill Reduces emissions."


def test_fallback_text_when_no_title_or_summary(db, mock_encoder):
    bill = models.Bill(
        bill_id="118-hr-99", congress=118, bill_type="hr", bill_number=99,
        title=None, summary=None, latest_action="", latest_action_date="2023-01-01",
        last_updated="2023-01-01",
    )
    db.add(bill)
    db.commit()

    pipeline = EmbeddingPipeline(db=db, batch_size=10)
    pipeline.run()

    texts_passed = mock_encoder.encode.call_args_list[0][0][0]
    assert texts_passed[0] == "118-hr-99"  # falls back to bill_id
```

- [ ] **Step 2: Run to confirm failure**

```bash
uv run pytest tests/ingestion/test_embedding_pipeline.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.ingestion.embedding_pipeline'`

- [ ] **Step 3: Implement `app/ingestion/embedding_pipeline.py`**

```python
from loguru import logger
from sentence_transformers import SentenceTransformer
from sqlalchemy.orm import Session
from app.config import settings
from app.db import models


class EmbeddingPipeline:
    """Batch-encode bills with SentenceTransformer, writing vectors to bills.embedding.

    The model is lazy-loaded on the first call to run() to avoid an eager 90 MB
    download at construction time and to keep settings.EMBEDDING_MODEL safe as a default.
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
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/ingestion/test_embedding_pipeline.py -v
```

Expected: 5 PASSED.

- [ ] **Step 5: Run full suite**

```bash
uv run pytest -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add app/ingestion/embedding_pipeline.py tests/ingestion/test_embedding_pipeline.py
git commit -m "feat: add embedding pipeline — batch-encode bills with sentence-transformers"
```

---

## Task 6: CLI `embed-bills` Command

**Files:**
- Modify: `app/cli.py`

No separate test — the pipeline itself is tested. Verify manually.

- [ ] **Step 1: Add `embed-bills` command to `app/cli.py`**

```python
@app.command()
def embed_bills(
    batch_size: int = typer.Option(64, help="Bills per encoding batch"),
    model: str = typer.Option(settings.EMBEDDING_MODEL, help="SentenceTransformer model name"),
):
    """Generate and store embeddings for bills with null embedding."""
    from app.ingestion.embedding_pipeline import EmbeddingPipeline

    logger.info(f"Starting embedding pipeline (batch_size={batch_size}, model={model})")
    with SessionLocal() as db:
        pipeline = EmbeddingPipeline(db=db, model_name=model, batch_size=batch_size)
        stats = pipeline.run()

    typer.echo(f"Done: {stats}")
```

- [ ] **Step 2: Smoke-test the CLI**

```bash
uv run python -m app.cli --help
```

Expected: `embed-bills` appears in the commands list.

```bash
uv run python -m app.cli embed-bills --help
```

Expected: help text with `--batch-size` and `--model` options.

- [ ] **Step 3: Commit**

```bash
git add app/cli.py
git commit -m "feat: add embed-bills CLI command"
```

---

## Running the Pipeline for Real

After Universe DL has populated the DB:

```bash
# Start DB
docker compose up -d postgres
uv run alembic upgrade head

# Run Universe DL (if not done already)
uv run python -m app.cli universe-dl /path/to/congress/data/bills/

# Generate embeddings (takes ~10 min for full corpus on CPU)
uv run python -m app.cli embed-bills --batch-size 128

# Check progress
psql $DATABASE_URL -c "SELECT COUNT(*) FROM bills WHERE embedding IS NULL;"
```

After embeddings are populated, add the pgvector index for fast ANN search (do this AFTER bulk loading — creating the index on an empty table is useless):

```sql
-- Run via psql or a one-off Alembic migration after bulk load
CREATE INDEX CONCURRENTLY ON bills USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

> **Note:** `lists = 100` is suitable for up to ~1M bills. Tune to `sqrt(row_count)` for larger datasets.

---

## Open Questions / Deferred

1. **Subjects from Daily DL:** The daily pipeline upserts bills — subjects are now included. Subjects are fully replaced on every upsert (`bill.subjects = [...]`), so upstream removals are handled correctly — no stale subjects persist.
2. **Re-embedding on title/summary change:** When `upsert_bill` updates a bill's text fields, it currently leaves `embedding` intact (stale). A future improvement: set `bill.embedding = None` in `upsert_bill` when `title` or `summary` changes, so the embedding pipeline picks it up on next run.
3. **GPU acceleration:** `SentenceTransformer.encode()` uses GPU if available (torch detects CUDA automatically). No code change required.
