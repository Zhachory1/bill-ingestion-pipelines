# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A RAG (Retrieval-Augmented Generation) chatbot for querying US legislative bills. Bills are ingested from Congress.gov and GovTrack APIs, stored in PostgreSQL with semantic embeddings, and served via a FastAPI chatbot interface.

## Development Setup

**Package manager**: `uv` (installed in `.venv/`)

```bash
uv sync                      # Install/sync dependencies
uv run pytest                # Run all tests
uv run pytest tests/path/test_file.py::test_name  # Run single test
uv run uvicorn app.main:app --reload  # Start dev server
```

**Environment**: Copy `.env.example` to `.env` and fill in API keys before running.

**Database** (PostgreSQL via Docker Compose):
```bash
docker compose up -d postgres   # Start database
uv run alembic upgrade head     # Apply migrations
uv run alembic revision --autogenerate -m "description"  # New migration
```

## Architecture

The system is a standard RAG pipeline with three main subsystems:

**1. ETL / Ingestion**
- Fetches bills from `CONGRESS_GOV_API_KEY` / `GOVTRACK_API_KEY` in configurable batches (`ETL_BATCH_SIZE`, `ETL_RATE_LIMIT_DELAY`)
- Processes text with spaCy, creates embeddings via `sentence-transformers` (`EMBEDDING_MODEL=all-MiniLM-L6-v2`)
- Stores bills + vector embeddings in PostgreSQL

**2. Retrieval**
- Default strategy: `semantic` (cosine similarity over embeddings)
- Configured via `DEFAULT_RETRIEVAL_STRATEGY` and `MAX_RESULTS`
- Likely uses pgvector or manual similarity in SQLAlchemy

**3. Chat Interface (FastAPI)**
- Server at `HOST:PORT` (default `0.0.0.0:8000`)
- LLM provider switchable: `LLM_PROVIDER=openai|anthropic`
- Model/temperature/token config in `.env`

## Key Dependencies

| Package | Role |
|---------|------|
| `fastapi` + `uvicorn` | Web server |
| `sqlalchemy` + `alembic` + `psycopg2` | DB ORM + migrations |
| `sentence-transformers` + `torch` | Semantic embeddings |
| `openai` + `anthropic` | LLM backends |
| `spacy` | NLP pre-processing |
| `pydantic-settings` | Typed settings from `.env` |
| `loguru` | Logging |
| `typer` | CLI commands (ETL, admin) |

## Data Directories

- `data/raw/` — Downloaded bill source files (gitignored except `.gitkeep`)
- `data/processed/` — Cleaned/chunked bill text
- `data/cache/` — Embedding or API response cache
