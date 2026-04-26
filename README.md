# Bill Retrieval Chatbot

RAG chatbot for querying US congressional bills. Bills are ingested from the Congress.gov BILLSTATUS XML corpus, stored in PostgreSQL with pgvector semantic embeddings, and served via a FastAPI REST API.

## Quick Start

```bash
# Install dependencies
uv sync

# Copy env template and fill in values
cp .env.example .env

# Start PostgreSQL (requires Docker)
docker compose up -d postgres

# Apply database migrations
uv run alembic upgrade head
```

## Architecture

```
BILLSTATUS XML corpus
        │
        ▼
  app/ingestion/
    xml_parser.py      — parse XML → ParsedBill dataclass
    db_writer.py       — upsert bills, sponsors, subjects to PostgreSQL
    universe_dl.py     — bulk ingest from corpus directory (with checkpoint/resume)
    daily_dl.py        — incremental ingest via git diff HEAD@{1}
    embedding_pipeline.py — batch-encode bills with SentenceTransformer → pgvector
        │
        ▼
  PostgreSQL (pgvector)
    bills              — bill metadata + 384-dim embedding vector
    sponsors           — congressmember metadata
    legislative_subjects — subject tags (many-to-many via bill_subjects)
    parse_failures     — dead-letter queue for malformed XML
    ingest_checkpoints — resume markers for universe-dl
        │
        ▼
  app/api/
    bills.py           — GET /api/bills/{id}, GET /api/bills/{id}/text
    search.py          — GET /api/search?q= (pgvector cosine similarity)
    schemas.py         — Pydantic response models
    deps.py            — get_db FastAPI dependency
```

## CLI Commands

```bash
# Bulk ingest from BILLSTATUS corpus
uv run python -m app.cli universe-dl /path/to/congress/data/bills

# Incremental ingest (run after git pull on the congress repo)
uv run python -m app.cli daily-dl /path/to/congress

# Generate embeddings for all un-embedded bills
uv run python -m app.cli embed-bills
```

## API

```bash
# Start dev server
uv run uvicorn app.main:app --reload

# Bill detail
curl http://localhost:8000/api/bills/118-hr-1234

# Bill text (for LLM context)
curl http://localhost:8000/api/bills/118-hr-1234/text

# Semantic search
curl "http://localhost:8000/api/search?q=climate+change&limit=5"

# Interactive docs
open http://localhost:8000/docs
```

## Docker Compose Profiles

```bash
# ETL profile: run migrations then bulk ingest
CORPUS_DIR=/path/to/corpus docker compose --profile universe-dl up

# Daily profile: run migrations then incremental ingest
REPO_PATH=/path/to/congress docker compose --profile daily-dl up
```

## Development

```bash
# Run tests
uv run pytest

# Run a single test
uv run pytest tests/ingestion/test_xml_parser.py::test_parse_valid_bill -v

# New migration
uv run alembic revision --autogenerate -m "description"
```

## Environment Variables

See `.env.example` for the full list. Key variables:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///:memory:` | PostgreSQL connection string |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | SentenceTransformer model name |
| `ETL_BATCH_SIZE` | `100` | Files/bills per batch |
| `LLM_PROVIDER` | `anthropic` | `anthropic` or `openai` |
| `LLM_MODEL` | `claude-opus-4-5` | Model ID for the chatbot |
| `ANTHROPIC_API_KEY` | — | Required for Anthropic LLM |
| `OPENAI_API_KEY` | — | Required for OpenAI LLM |

## Data Sources

- **Bulk corpus**: [unitedstates/congress](https://github.com/unitedstates/congress) — BILLSTATUS XML for all bills since the 93rd Congress
- **Incremental updates**: same repo, tracked via git diff

## Notes

- The `embedding` column uses `pgvector`'s `vector(384)` type; requires the `pgvector/pgvector:pg16` Docker image (not plain `postgres:16`)
- Unit tests use SQLite in-memory; `_vector_search` is mocked since `<=>` is PostgreSQL-only
- `universe-dl` writes a checkpoint after each batch; re-running resumes from the last processed file
