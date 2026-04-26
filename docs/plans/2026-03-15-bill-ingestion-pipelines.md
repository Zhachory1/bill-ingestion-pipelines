# Bill Data Ingestion Pipelines Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build two ingestion pipelines — Universe DL (bulk historical load) and Daily DL (incremental delta updates) — that parse BILLSTATUS XML from the `unitedstates/congress` scraper into the PostgreSQL Bill DB.

**Architecture:** Shared `BillStatusParser` (lxml) extracts structured data from GPO BILLSTATUS XML. Universe DL walks local corpus directory in batches with checkpoint recovery. Daily DL uses `git diff` on scraped repo to find changed files and upserts only deltas. Both pipelines write to same PostgreSQL schema via SQLAlchemy and invoke via Typer CLI commands.

**Tech Stack:** Python 3.12, `uv`, SQLAlchemy 2.x, Alembic, lxml, GitPython, loguru, Typer, PostgreSQL + pgvector (Docker Compose).

---

## Prerequisites

Before starting:
- Docker Desktop running: `docker compose up -d postgres`
- `usc-run` CLI available: `pip install congress` or follow https://github.com/unitedstates/congress
- `.env` copied from `.env.example` with real values

---

### Task 0: Docker Compose

**Files:**
- Create: `docker-compose.yml`

**Step 1: Create docker-compose.yml**

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-bills}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-bills}
      POSTGRES_DB: ${POSTGRES_DB:-bills}
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-bills}"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

Using `pgvector/pgvector:pg16` image — has pgvector extension pre-installed; no custom init script needed.

**Step 2: Verify it starts**

```bash
docker compose up -d postgres
docker compose ps
```

Expected: postgres container in `healthy` state.

**Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add Docker Compose with pgvector/pg16 postgres"
```

---

### Task 1: Project Scaffolding

**Files:**
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `app/db/__init__.py`
- Create: `app/db/session.py`
- Create: `app/ingestion/__init__.py`
- Create: `pyproject.toml`
- Create: `alembic.ini`
- Create: `alembic/env.py`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "bill-retrieval-chatbot"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi",
    "uvicorn[standard]",
    "sqlalchemy>=2.0",
    "alembic",
    "psycopg2-binary",
    "pgvector",
    "lxml",
    "gitpython",
    "loguru",
    "typer",
    "pydantic-settings",
    "sentence-transformers",
    "openai",
    "anthropic",
    "spacy",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-cov", "httpx"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

**Step 2: Install dependencies**

```bash
uv sync
```

**Step 3: Create app/config.py**

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    LOG_LEVEL: str = "INFO"
    ETL_BATCH_SIZE: int = 100
    ETL_RATE_LIMIT_DELAY: float = 1.0
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIM: int = 384

    class Config:
        env_file = ".env"

settings = Settings()
```

**Step 4: Create app/db/session.py**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import settings

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

class Base(DeclarativeBase):
    pass
```

**Step 5: Initialize Alembic**

```bash
uv run alembic init alembic
```

Then edit `alembic/env.py` to import `Base` and use `settings.DATABASE_URL`. Note: `app.db.models` is imported here only to register models with `Base.metadata` — it won't exist until Task 2, so don't run alembic until then.

```python
from app.db.session import Base, engine
from app.db import models  # noqa: F401 — registers models with Base.metadata

target_metadata = Base.metadata

def run_migrations_online():
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
```

**Step 6: Create empty test directory**

```bash
mkdir -p tests/ingestion
touch tests/__init__.py tests/ingestion/__init__.py
```

**Step 7: Commit**

```bash
git add pyproject.toml alembic.ini alembic/ app/ tests/
git commit -m "feat: scaffold project structure with config, db session, and alembic"
```

---

### Task 2: Database Schema

**Files:**
- Create: `app/db/models.py`
- Create: `alembic/versions/<hash>_create_bill_tables.py` (auto-generated)

**Step 1: Write the test (schema round-trip)**

```python
# tests/test_models.py
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.db import models  # noqa

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_bill_insert_and_retrieve(db):
    bill = models.Bill(
        bill_id="118-hr-1234",
        congress=118,
        bill_type="hr",
        bill_number=1234,
        title="A Test Bill",
        latest_action="Passed House",
        latest_action_date="2023-01-15",
        last_updated="2023-01-15T10:00:00",
    )
    db.add(bill)
    db.commit()
    result = db.query(models.Bill).filter_by(bill_id="118-hr-1234").one()
    assert result.title == "A Test Bill"

def test_sponsor_join_table(db):
    bill = models.Bill(bill_id="118-hr-1", congress=118, bill_type="hr", bill_number=1, title="T", latest_action="", latest_action_date="2023-01-01", last_updated="2023-01-01")
    sponsor = models.Sponsor(bioguide_id="A000001", full_name="Jane Doe", party="D", state="CA")
    bill.sponsors.append(sponsor)
    db.add(bill)
    db.commit()
    assert db.query(models.Bill).first().sponsors[0].full_name == "Jane Doe"

def test_parse_failure_log(db):
    failure = models.ParseFailure(file_path="/data/bills/118/hr/1/fdsys_billstatus.xml", error_message="KeyError: billType")
    db.add(failure)
    db.commit()
    assert db.query(models.ParseFailure).count() == 1

def test_bill_embedding_column_exists(db):
    bill = models.Bill(
        bill_id="118-hr-9", congress=118, bill_type="hr", bill_number=9,
        title="Embedding Test", latest_action="", latest_action_date="2023-01-01", last_updated="2023-01-01",
    )
    db.add(bill)
    db.commit()
    result = db.query(models.Bill).filter_by(bill_id="118-hr-9").one()
    assert result.embedding is None  # null until embedding pipeline runs
```

**Step 2: Run the test to see it fail**

```bash
uv run pytest tests/test_models.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.db.models'`

**Step 3: Create app/db/models.py**

The `embedding` column uses `pgvector.sqlalchemy.Vector`. In SQLite (used for unit tests) this column type falls back to a nullable `Text` column — tests that don't touch embeddings are unaffected. The real pgvector dimension is set via `settings.EMBEDDING_DIM` (384 for `all-MiniLM-L6-v2`).

```python
from datetime import datetime
from sqlalchemy import Table, Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship, Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from app.db.session import Base
from app.config import settings

# Join tables
bill_sponsors = Table(
    "bill_to_sponsor", Base.metadata,
    Column("bill_id", String, ForeignKey("bills.bill_id"), primary_key=True),
    Column("bioguide_id", String, ForeignKey("sponsors.bioguide_id"), primary_key=True),
)

bill_cosponsors = Table(
    "bill_to_cosponsor", Base.metadata,
    Column("bill_id", String, ForeignKey("bills.bill_id"), primary_key=True),
    Column("bioguide_id", String, ForeignKey("sponsors.bioguide_id"), primary_key=True),
)

class Bill(Base):
    __tablename__ = "bills"

    bill_id: Mapped[str] = mapped_column(String, primary_key=True)  # e.g. "118-hr-1234"
    congress: Mapped[int] = mapped_column(Integer, nullable=False)
    bill_type: Mapped[str] = mapped_column(String(10), nullable=False)
    bill_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=True)
    latest_action: Mapped[str] = mapped_column(Text, nullable=True)
    latest_action_date: Mapped[str] = mapped_column(String(20), nullable=True)
    last_updated: Mapped[str] = mapped_column(String(30), nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.EMBEDDING_DIM), nullable=True)

    sponsors: Mapped[list["Sponsor"]] = relationship("Sponsor", secondary=bill_sponsors, back_populates="sponsored_bills")
    cosponsors: Mapped[list["Sponsor"]] = relationship("Sponsor", secondary=bill_cosponsors, back_populates="cosponsored_bills")

class Sponsor(Base):
    __tablename__ = "sponsors"

    bioguide_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(200), nullable=True)
    party: Mapped[str] = mapped_column(String(5), nullable=True)
    state: Mapped[str] = mapped_column(String(5), nullable=True)

    sponsored_bills: Mapped[list["Bill"]] = relationship("Bill", secondary=bill_sponsors, back_populates="sponsors")
    cosponsored_bills: Mapped[list["Bill"]] = relationship("Bill", secondary=bill_cosponsors, back_populates="cosponsors")

class ParseFailure(Base):
    """Dead letter queue: XML files that failed to parse."""
    __tablename__ = "parse_failures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class IngestCheckpoint(Base):
    """Tracks Universe DL progress so it can resume after a crash."""
    __tablename__ = "ingest_checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline: Mapped[str] = mapped_column(String(50), nullable=False)  # "universe" or "daily"
    last_processed: Mapped[str] = mapped_column(Text, nullable=True)   # directory or git commit SHA
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_models.py -v
```

Expected: 4 PASSED

**Step 5: Generate migration and enable pgvector extension**

The migration must enable the `vector` extension before creating the `bills` table. Edit the generated migration to add this at the top of `upgrade()`:

```python
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # ... rest of autogenerated table creation ...
```

```bash
uv run alembic revision --autogenerate -m "create bill tables"
# Edit the generated file to add the CREATE EXTENSION line above
uv run alembic upgrade head
```

**Step 6: Commit**

```bash
git add app/db/models.py alembic/versions/ tests/test_models.py
git commit -m "feat: add bill schema with pgvector embedding column"
```

---

### Task 3: Shared XML Parser

The BILLSTATUS XML schema from GPO looks like this (abbreviated):
```xml
<billStatus>
  <bill>
    <billType>HR</billType>
    <billNumber>1234</billNumber>
    <congress>118</congress>
    <title>A Bill To...</title>
    <sponsors><item><bioguideId>A000001</bioguideId>...</item></sponsors>
    <cosponsors>...</cosponsors>
    <actions>
      <item><actionDate>2023-01-15</actionDate><text>Passed House.</text></item>
    </actions>
    <summaries><summary><text>...</text></summary></summaries>
    <updateDate>2023-01-15T10:00:00Z</updateDate>
  </bill>
</billStatus>
```

**Files:**
- Create: `app/ingestion/xml_parser.py`
- Create: `tests/ingestion/test_xml_parser.py`
- Create: `tests/ingestion/fixtures/sample_billstatus.xml`

**Step 1: Create the fixture XML**

```xml
<!-- tests/ingestion/fixtures/sample_billstatus.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<billStatus>
  <bill>
    <billType>HR</billType>
    <billNumber>1234</billNumber>
    <congress>118</congress>
    <title>A Bill To Test Parsing</title>
    <updateDate>2023-01-15T10:00:00Z</updateDate>
    <sponsors>
      <item>
        <bioguideId>A000001</bioguideId>
        <fullName>Rep. Jane Doe [D-CA-1]</fullName>
        <party>D</party>
        <state>CA</state>
      </item>
    </sponsors>
    <cosponsors>
      <item>
        <bioguideId>B000002</bioguideId>
        <fullName>Rep. John Smith [R-TX-5]</fullName>
        <party>R</party>
        <state>TX</state>
      </item>
    </cosponsors>
    <actions>
      <item>
        <actionDate>2023-01-10</actionDate>
        <text>Introduced in House</text>
      </item>
      <item>
        <actionDate>2023-01-15</actionDate>
        <text>Passed House</text>
      </item>
    </actions>
    <summaries>
      <summary>
        <text>This bill does a thing.</text>
      </summary>
    </summaries>
  </bill>
</billStatus>
```

Also create three additional fixture files with distinct bill identities for use in integration tests:

```xml
<!-- tests/ingestion/fixtures/sample_billstatus_s5.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<billStatus>
  <bill>
    <billType>S</billType>
    <billNumber>5</billNumber>
    <congress>118</congress>
    <title>A Senate Bill</title>
    <updateDate>2023-02-01T10:00:00Z</updateDate>
    <sponsors><item><bioguideId>C000003</bioguideId><fullName>Sen. Alice Lee [D-NY]</fullName><party>D</party><state>NY</state></item></sponsors>
    <cosponsors/>
    <actions><item><actionDate>2023-02-01</actionDate><text>Introduced in Senate</text></item></actions>
    <summaries><summary><text>Senate bill summary.</text></summary></summaries>
  </bill>
</billStatus>
```

```xml
<!-- tests/ingestion/fixtures/sample_billstatus_hr100.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<billStatus>
  <bill>
    <billType>HR</billType>
    <billNumber>100</billNumber>
    <congress>117</congress>
    <title>An Older House Bill</title>
    <updateDate>2022-06-15T10:00:00Z</updateDate>
    <sponsors><item><bioguideId>D000004</bioguideId><fullName>Rep. Bob Ray [R-FL-3]</fullName><party>R</party><state>FL</state></item></sponsors>
    <cosponsors/>
    <actions><item><actionDate>2022-06-15</actionDate><text>Passed House</text></item></actions>
    <summaries><summary><text>Older bill summary.</text></summary></summaries>
  </bill>
</billStatus>
```

**Step 2: Write the failing tests**

```python
# tests/ingestion/test_xml_parser.py
import pytest
from pathlib import Path
from app.ingestion.xml_parser import BillStatusParser, ParsedBill, ParsedSponsor

FIXTURE = Path(__file__).parent / "fixtures" / "sample_billstatus.xml"

def test_parses_bill_id():
    result: ParsedBill = BillStatusParser.parse(FIXTURE)
    assert result.bill_id == "118-hr-1234"

def test_parses_bill_metadata():
    result = BillStatusParser.parse(FIXTURE)
    assert result.congress == 118
    assert result.bill_type == "hr"
    assert result.bill_number == 1234
    assert result.title == "A Bill To Test Parsing"

def test_parses_latest_action():
    """Actions sorted by date; latest_action is most recent."""
    result = BillStatusParser.parse(FIXTURE)
    assert result.latest_action == "Passed House"
    assert result.latest_action_date == "2023-01-15"

def test_parses_sponsors():
    result = BillStatusParser.parse(FIXTURE)
    assert len(result.sponsors) == 1
    assert result.sponsors[0].bioguide_id == "A000001"
    assert result.sponsors[0].party == "D"

def test_parses_cosponsors():
    result = BillStatusParser.parse(FIXTURE)
    assert len(result.cosponsors) == 1
    assert result.cosponsors[0].bioguide_id == "B000002"

def test_parses_summary():
    result = BillStatusParser.parse(FIXTURE)
    assert "does a thing" in result.summary

def test_raises_on_missing_required_field(tmp_path):
    """Parser must raise ValueError (not silently produce garbage) if billType is missing."""
    bad_xml = tmp_path / "bad.xml"
    bad_xml.write_text("<billStatus><bill><billNumber>1</billNumber></bill></billStatus>")
    with pytest.raises(ValueError, match="billType"):
        BillStatusParser.parse(bad_xml)
```

**Step 3: Run tests to confirm failure**

```bash
uv run pytest tests/ingestion/test_xml_parser.py -v
```

Expected: `ModuleNotFoundError`

**Step 4: Implement the parser**

```python
# app/ingestion/xml_parser.py
from dataclasses import dataclass, field
from pathlib import Path
from lxml import etree

@dataclass
class ParsedSponsor:
    bioguide_id: str
    full_name: str | None
    party: str | None
    state: str | None

@dataclass
class ParsedBill:
    bill_id: str          # e.g. "118-hr-1234"
    congress: int
    bill_type: str        # lowercased: "hr", "s", "hjres", etc.
    bill_number: int
    title: str | None
    summary: str | None
    latest_action: str | None
    latest_action_date: str | None
    last_updated: str | None
    sponsors: list[ParsedSponsor] = field(default_factory=list)
    cosponsors: list[ParsedSponsor] = field(default_factory=list)

class BillStatusParser:
    @staticmethod
    def parse(xml_path: Path) -> ParsedBill:
        """Parse a BILLSTATUS XML file into a ParsedBill dataclass.

        Raises ValueError if required fields (billType, billNumber, congress) are missing.
        """
        tree = etree.parse(str(xml_path))
        bill = tree.find(".//bill")

        def req(tag: str) -> str:
            el = bill.find(tag)
            if el is None or not el.text:
                raise ValueError(f"Required field '{tag}' missing in {xml_path}")
            return el.text.strip()

        def opt(tag: str) -> str | None:
            el = bill.find(tag)
            return el.text.strip() if el is not None and el.text else None

        bill_type = req("billType").lower()
        bill_number = int(req("billNumber"))
        congress = int(req("congress"))
        bill_id = f"{congress}-{bill_type}-{bill_number}"

        actions = bill.findall(".//actions/item")
        actions_sorted = sorted(
            [(a.findtext("actionDate", ""), a.findtext("text", "")) for a in actions],
            key=lambda x: x[0],
            reverse=True,
        )
        latest_action_date, latest_action = (actions_sorted[0] if actions_sorted else ("", ""))

        def parse_sponsors(tag: str) -> list[ParsedSponsor]:
            return [
                ParsedSponsor(
                    bioguide_id=item.findtext("bioguideId", "").strip(),
                    full_name=item.findtext("fullName"),
                    party=item.findtext("party"),
                    state=item.findtext("state"),
                )
                for item in bill.findall(f".//{tag}/item")
                if item.findtext("bioguideId")
            ]

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
            sponsors=parse_sponsors("sponsors"),
            cosponsors=parse_sponsors("cosponsors"),
        )
```

**Step 5: Run tests to verify**

```bash
uv run pytest tests/ingestion/test_xml_parser.py -v
```

Expected: 7 PASSED

**Step 6: Commit**

```bash
git add app/ingestion/xml_parser.py tests/ingestion/
git commit -m "feat: add shared BillStatusParser for BILLSTATUS XML"
```

---

### Task 4: DB Writer (Upsert Logic)

Both pipelines share a single writer that takes a `ParsedBill` and upserts it into PostgreSQL.

**Files:**
- Create: `app/ingestion/db_writer.py`
- Create: `tests/ingestion/test_db_writer.py`

**Step 1: Write the failing tests**

```python
# tests/ingestion/test_db_writer.py
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.db import models  # noqa
from app.ingestion.db_writer import upsert_bill
from app.ingestion.xml_parser import ParsedBill, ParsedSponsor

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

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
        sponsors=[ParsedSponsor("A000001", "Jane Doe", "D", "CA")],
        cosponsors=[],
    )
    defaults.update(kwargs)
    return ParsedBill(**defaults)

def test_insert_new_bill(db):
    upsert_bill(db, make_parsed_bill())
    db.commit()
    bill = db.query(models.Bill).one()
    assert bill.bill_id == "118-hr-1"
    assert bill.title == "Test Bill"

def test_upsert_updates_existing_bill(db):
    upsert_bill(db, make_parsed_bill(title="Old Title"))
    db.commit()
    upsert_bill(db, make_parsed_bill(title="New Title", latest_action="Enacted"))
    db.commit()
    bills = db.query(models.Bill).all()
    assert len(bills) == 1  # no duplicate
    assert bills[0].title == "New Title"
    assert bills[0].latest_action == "Enacted"

def test_upsert_creates_sponsors(db):
    upsert_bill(db, make_parsed_bill())
    db.commit()
    sponsor = db.query(models.Sponsor).filter_by(bioguide_id="A000001").one()
    assert sponsor.full_name == "Jane Doe"
    bill = db.query(models.Bill).one()
    assert len(bill.sponsors) == 1

def test_upsert_does_not_duplicate_sponsors(db):
    upsert_bill(db, make_parsed_bill())
    upsert_bill(db, make_parsed_bill())
    db.commit()
    assert db.query(models.Sponsor).count() == 1
```

**Step 2: Run to see failures**

```bash
uv run pytest tests/ingestion/test_db_writer.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.ingestion.db_writer'`

**Step 3: Implement the writer**

```python
# app/ingestion/db_writer.py
from sqlalchemy.orm import Session
from app.db import models
from app.ingestion.xml_parser import ParsedBill, ParsedSponsor

def _upsert_sponsor(db: Session, s: ParsedSponsor) -> None:
    existing = db.get(models.Sponsor, s.bioguide_id)
    if existing is None:
        db.add(models.Sponsor(
            bioguide_id=s.bioguide_id,
            full_name=s.full_name,
            party=s.party,
            state=s.state,
        ))
    else:
        existing.full_name = s.full_name
        existing.party = s.party
        existing.state = s.state

def upsert_bill(db: Session, parsed: ParsedBill) -> None:
    """Insert or update a Bill and its sponsor/cosponsor relationships."""
    existing = db.get(models.Bill, parsed.bill_id)

    if existing is None:
        bill = models.Bill(
            bill_id=parsed.bill_id,
            congress=parsed.congress,
            bill_type=parsed.bill_type,
            bill_number=parsed.bill_number,
            title=parsed.title,
            summary=parsed.summary,
            latest_action=parsed.latest_action,
            latest_action_date=parsed.latest_action_date,
            last_updated=parsed.last_updated,
        )
        db.add(bill)
        db.flush()
    else:
        bill = existing
        bill.title = parsed.title
        bill.summary = parsed.summary
        bill.latest_action = parsed.latest_action
        bill.latest_action_date = parsed.latest_action_date
        bill.last_updated = parsed.last_updated

    for s in parsed.sponsors:
        _upsert_sponsor(db, s)
    for s in parsed.cosponsors:
        _upsert_sponsor(db, s)
    db.flush()

    bill.sponsors = [db.get(models.Sponsor, s.bioguide_id) for s in parsed.sponsors]
    bill.cosponsors = [db.get(models.Sponsor, s.bioguide_id) for s in parsed.cosponsors]
```

**Step 4: Run tests**

```bash
uv run pytest tests/ingestion/test_db_writer.py -v
```

Expected: 4 PASSED

**Step 5: Commit**

```bash
git add app/ingestion/db_writer.py tests/ingestion/test_db_writer.py
git commit -m "feat: add upsert_bill writer with sponsor deduplication"
```

---

### Task 5: Universe DL Pipeline

**Files:**
- Create: `app/ingestion/universe_dl.py`
- Create: `tests/ingestion/test_universe_dl.py`

The checkpoint pattern (storing last-processed file path in DB) is at-least-once delivery. If the pipeline crashes mid-batch it reprocesses the entire last batch — safe because `upsert_bill` is idempotent.

**Step 1: Write failing tests**

```python
# tests/ingestion/test_universe_dl.py
import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.db import models  # noqa
from app.ingestion.universe_dl import UniverseDL

FIXTURE_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

@pytest.fixture
def xml_corpus(tmp_path):
    """Mini corpus: 2 XML files with distinct bill identities."""
    (tmp_path / "118/hr/1234").mkdir(parents=True)
    (tmp_path / "118/s/5").mkdir(parents=True)
    import shutil
    shutil.copy(FIXTURE_DIR / "sample_billstatus.xml", tmp_path / "118/hr/1234/fdsys_billstatus.xml")
    shutil.copy(FIXTURE_DIR / "sample_billstatus_s5.xml", tmp_path / "118/s/5/fdsys_billstatus.xml")
    return tmp_path

def test_finds_all_xml_files(db, xml_corpus):
    dl = UniverseDL(db=db, corpus_dir=xml_corpus, batch_size=10)
    files = dl._enumerate_xml_files()
    assert len(files) == 2

def test_processes_all_files(db, xml_corpus):
    dl = UniverseDL(db=db, corpus_dir=xml_corpus, batch_size=10)
    stats = dl.run()
    assert stats["processed"] == 2
    assert stats["failed"] == 0

def test_failed_parse_logged_to_db(db, tmp_path):
    bad_xml = tmp_path / "bad.xml"
    bad_xml.write_text("<billStatus><bill></bill></billStatus>")
    dl = UniverseDL(db=db, corpus_dir=tmp_path, batch_size=10)
    stats = dl.run()
    assert stats["failed"] == 1
    assert db.query(models.ParseFailure).count() == 1

def test_checkpoint_saved_per_batch(db, xml_corpus):
    dl = UniverseDL(db=db, corpus_dir=xml_corpus, batch_size=1)
    dl.run()
    checkpoint = db.query(models.IngestCheckpoint).filter_by(pipeline="universe").first()
    assert checkpoint is not None

def test_resumes_from_checkpoint(db, xml_corpus):
    """Files before the checkpoint path are skipped."""
    files = sorted(xml_corpus.rglob("*.xml"))
    checkpoint = models.IngestCheckpoint(pipeline="universe", last_processed=str(files[0]))
    db.add(checkpoint)
    db.commit()

    dl = UniverseDL(db=db, corpus_dir=xml_corpus, batch_size=10)
    stats = dl.run()
    assert stats["processed"] == 1
```

**Step 2: Run to confirm failure**

```bash
uv run pytest tests/ingestion/test_universe_dl.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Implement UniverseDL**

```python
# app/ingestion/universe_dl.py
from dataclasses import dataclass, field
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
        self.db.add(models.ParseFailure(
            file_path=str(path),
            error_message=str(error),
        ))
        self.db.commit()

    def run(self) -> dict:
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
```

**Step 4: Run tests**

```bash
uv run pytest tests/ingestion/test_universe_dl.py -v
```

Expected: 5 PASSED

**Step 5: Commit**

```bash
git add app/ingestion/universe_dl.py tests/ingestion/test_universe_dl.py
git commit -m "feat: add Universe DL pipeline with checkpointing and dead-letter logging"
```

---

### Task 6: Daily DL Pipeline

**Files:**
- Create: `app/ingestion/daily_dl.py`
- Create: `tests/ingestion/test_daily_dl.py`

Using `git diff --name-status HEAD@{1} HEAD` (reflog-based) rather than `HEAD~1..HEAD` (commit-based): the reflog version catches all changes since the last time HEAD moved, including after a `git pull` with multiple commits. More robust for the real daily-pull workflow.

**Step 1: Write failing tests**

```python
# tests/ingestion/test_daily_dl.py
import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.db import models  # noqa
from app.ingestion.daily_dl import DailyDL, DiffEntry

FIXTURE_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_parses_git_diff_output():
    raw = "A\tdata/bills/118/hr/1/fdsys_billstatus.xml\nM\tdata/bills/118/s/5/fdsys_billstatus.xml\nD\tdata/bills/old/file.xml"
    entries = DailyDL._parse_diff_output(raw)
    assert len(entries) == 2  # D (deleted) ignored
    assert entries[0] == DiffEntry(status="A", path=Path("data/bills/118/hr/1/fdsys_billstatus.xml"))
    assert entries[1] == DiffEntry(status="M", path=Path("data/bills/118/s/5/fdsys_billstatus.xml"))

def test_only_processes_xml_files():
    raw = "A\tdata/bills/118/hr/1/fdsys_billstatus.xml\nM\tdata/bills/118/hr/2/README.md"
    entries = DailyDL._parse_diff_output(raw)
    assert len(entries) == 1

def test_insert_on_added(db, tmp_path):
    import shutil
    bill_path = tmp_path / "fdsys_billstatus.xml"
    shutil.copy(FIXTURE_DIR / "sample_billstatus.xml", bill_path)

    entries = [DiffEntry(status="A", path=bill_path)]
    dl = DailyDL(db=db, repo_path=tmp_path)
    stats = dl._process_entries(entries)

    assert stats["inserted"] == 1
    assert db.query(models.Bill).count() == 1

def test_update_on_modified(db, tmp_path):
    import shutil
    bill_path = tmp_path / "fdsys_billstatus.xml"
    shutil.copy(FIXTURE_DIR / "sample_billstatus.xml", bill_path)

    # Pre-insert so the bill exists — "M" means it was already in the repo
    from app.ingestion.xml_parser import BillStatusParser
    from app.ingestion.db_writer import upsert_bill
    parsed = BillStatusParser.parse(bill_path)
    upsert_bill(db, parsed)
    db.commit()

    entries = [DiffEntry(status="M", path=bill_path)]
    dl = DailyDL(db=db, repo_path=tmp_path)
    stats = dl._process_entries(entries)

    assert stats["updated"] == 1
    assert db.query(models.Bill).count() == 1  # still 1, not 2

def test_failed_parse_goes_to_dead_letter(db, tmp_path):
    bad_xml = tmp_path / "bad.xml"
    bad_xml.write_text("<billStatus><bill></bill></billStatus>")

    entries = [DiffEntry(status="A", path=bad_xml)]
    dl = DailyDL(db=db, repo_path=tmp_path)
    dl._process_entries(entries)

    assert db.query(models.ParseFailure).count() == 1
```

**Step 2: Run to confirm failures**

```bash
uv run pytest tests/ingestion/test_daily_dl.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Implement DailyDL**

```python
# app/ingestion/daily_dl.py
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
    def __init__(self, db: Session, repo_path: Path):
        self.db = db
        self.repo_path = repo_path

    @staticmethod
    def _parse_diff_output(raw: str) -> list[DiffEntry]:
        """Parse `git diff --name-status` output. Ignores deletions and non-XML files."""
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

    def _get_changed_files(self) -> list[DiffEntry]:
        result = subprocess.run(
            ["git", "diff", "--name-status", "HEAD@{1}", "HEAD"],
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
        logger.info("Daily DL: fetching changed files from git diff...")
        entries = self._get_changed_files()
        logger.info(f"Found {len(entries)} changed XML files.")
        stats = self._process_entries(entries)
        logger.info(f"Daily DL complete: {stats}")
        return stats
```

**Step 4: Run tests**

```bash
uv run pytest tests/ingestion/test_daily_dl.py -v
```

Expected: 5 PASSED

**Step 5: Commit**

```bash
git add app/ingestion/daily_dl.py tests/ingestion/test_daily_dl.py
git commit -m "feat: add Daily DL pipeline with git-diff delta detection and dead-letter queue"
```

---

### Task 7: CLI Entry Points

**Files:**
- Create: `app/cli.py`

**Step 1: Implement the CLI**

```python
# app/cli.py
from pathlib import Path
import typer
from loguru import logger
from app.db.session import SessionLocal
from app.config import settings

app = typer.Typer(help="Bill Retrieval Chatbot — ETL commands")

@app.command()
def universe_dl(
    corpus_dir: Path = typer.Argument(..., help="Path to the unzipped BILLSTATUS corpus"),
    batch_size: int = typer.Option(settings.ETL_BATCH_SIZE, help="Files per batch"),
    resume: bool = typer.Option(True, help="Resume from last checkpoint if available"),
):
    """Run the Universe DL bulk ingestion pipeline."""
    from app.ingestion.universe_dl import UniverseDL

    if not corpus_dir.exists():
        typer.echo(f"Error: {corpus_dir} does not exist.", err=True)
        raise typer.Exit(1)

    logger.info(f"Starting Universe DL from {corpus_dir} (batch_size={batch_size})")
    with SessionLocal() as db:
        if not resume:
            from app.db import models
            db.query(models.IngestCheckpoint).filter_by(pipeline="universe").delete()
            db.commit()
        dl = UniverseDL(db=db, corpus_dir=corpus_dir, batch_size=batch_size)
        stats = dl.run()

    typer.echo(f"Done: {stats}")

@app.command()
def daily_dl(
    repo_path: Path = typer.Argument(..., help="Path to the local unitedstates/congress repo"),
):
    """Run the Daily DL incremental pipeline using git diff."""
    from app.ingestion.daily_dl import DailyDL

    if not (repo_path / ".git").exists():
        typer.echo(f"Error: {repo_path} is not a git repository.", err=True)
        raise typer.Exit(1)

    logger.info(f"Starting Daily DL from {repo_path}")
    with SessionLocal() as db:
        dl = DailyDL(db=db, repo_path=repo_path)
        stats = dl.run()

    typer.echo(f"Done: {stats}")

if __name__ == "__main__":
    app()
```

**Step 2: Test the CLI manually**

```bash
mkdir -p /tmp/empty-corpus
uv run python -m app.cli universe-dl /tmp/empty-corpus
uv run python -m app.cli --help
```

**Step 3: Commit**

```bash
git add app/cli.py
git commit -m "feat: add Typer CLI for universe-dl and daily-dl commands"
```

---

### Task 8: Full Integration Test

**Files:**
- Create: `tests/ingestion/test_integration.py`

**Step 1: Write integration test**

The corpus fixture uses three distinct fixture XMLs (hr-1234, s-5, hr-100) so each parses to a unique `bill_id`. The fourth file is intentionally malformed to test the dead-letter path.

```python
# tests/ingestion/test_integration.py
"""Integration test: runs the full Universe DL pipeline on a small fixture corpus."""
import shutil
import pytest
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.session import Base
from app.db import models  # noqa
from app.ingestion.universe_dl import UniverseDL

FIXTURE_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture
def corpus(tmp_path):
    """3 valid bills with distinct identities + 1 invalid XML."""
    cases = [
        ("118/hr/1234", "sample_billstatus.xml"),
        ("118/s/5",     "sample_billstatus_s5.xml"),
        ("117/hr/100",  "sample_billstatus_hr100.xml"),
    ]
    for subdir, fixture in cases:
        path = tmp_path / subdir
        path.mkdir(parents=True)
        shutil.copy(FIXTURE_DIR / fixture, path / "fdsys_billstatus.xml")

    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "fdsys_billstatus.xml").write_text("<billStatus><bill></bill></billStatus>")
    return tmp_path

@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()

def test_universe_dl_full_run(db, corpus):
    dl = UniverseDL(db=db, corpus_dir=corpus, batch_size=2)
    stats = dl.run()

    assert stats["processed"] == 3
    assert stats["failed"] == 1
    assert db.query(models.Bill).count() == 3
    assert db.query(models.ParseFailure).count() == 1

def test_universe_dl_is_idempotent(db, corpus):
    """Running twice must not duplicate bills."""
    dl = UniverseDL(db=db, corpus_dir=corpus, batch_size=10)
    dl.run()

    db.query(models.IngestCheckpoint).delete()
    db.commit()

    dl2 = UniverseDL(db=db, corpus_dir=corpus, batch_size=10)
    dl2.run()

    assert db.query(models.Bill).count() == 3  # still 3, not 6
```

**Step 2: Run integration tests**

```bash
uv run pytest tests/ingestion/test_integration.py -v
```

Expected: 2 PASSED

**Step 3: Run all tests**

```bash
uv run pytest -v
```

Expected: All green.

**Step 4: Final commit**

```bash
git add tests/ingestion/test_integration.py
git commit -m "test: add integration tests for Universe DL pipeline"
```

---

## Running the Pipelines for Real

### Universe DL (one-time bulk load)

```bash
# 1. Start DB
docker compose up -d postgres
uv run alembic upgrade head

# 2. Download the corpus
usc-run govinfo --bulkdata=BILLSTATUS

# 3. Run
uv run python -m app.cli universe-dl /path/to/congress/data/bills/
```

### Daily DL (incremental updates)

```bash
# 1. Update the local repo
cd /path/to/congress && usc-run bills

# 2. Run the delta pipeline
uv run python -m app.cli daily-dl /path/to/congress/
```

### Cron Setup

```cron
# Daily DL at 02:00 UTC
0 2 * * * cd /path/to/bill-retrieval-chatbot && uv run python -m app.cli daily-dl /path/to/congress/ >> /var/log/daily-dl.log 2>&1
```

---

## Open Questions / Deferred Scope

1. **Embedding pipeline:** Bills land in DB with `embedding = NULL`. Next step: separate pipeline runs `sentence-transformers` over `bills` rows where `embedding IS NULL` and writes the vector back.
2. **pgvector index:** After bulk load, add `CREATE INDEX ON bills USING ivfflat (embedding vector_cosine_ops)` for fast similarity search.
3. **Docker Compose services:** Add `universe-dl` and `daily-dl` one-shot service definitions for containerized execution.
