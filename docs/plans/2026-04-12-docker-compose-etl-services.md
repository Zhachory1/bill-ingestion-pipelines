# Docker Compose ETL Services Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add `migrate`, `universe-dl`, and `daily-dl` Docker Compose services so both pipelines can be run containerized without affecting the default `docker compose up` workflow.

**Architecture:** A single shared `Dockerfile` builds the app image. Three new services are gated behind Compose `profiles` so they never start accidentally. `migrate` runs `alembic upgrade head` and exits; `universe-dl` and `daily-dl` each depend on `migrate` completing successfully, then invoke the existing Typer CLI. Host corpus/repo directories are mounted as read-only (or read-write for daily-dl) volumes at fixed container paths.

**Tech Stack:** Docker, Docker Compose v2, Python 3.12-slim base image, `uv` for dependency installation.

---

## Prerequisites

- Docker Desktop running
- `.env` copied from `.env.example` with real values
- `uv.lock` committed (generated in Task 1)

---

### Task 1: Generate and commit uv lockfile

The Dockerfile will use `uv sync --frozen` for reproducible builds. A lockfile must exist first.

**Files:**
- Create: `uv.lock` (generated, not hand-written)

**Step 1: Generate the lockfile**

```bash
cd .worktrees/bill-ingestion-pipelines
uv lock
```

Expected: `uv.lock` created in the project root.

**Step 2: Verify it was created**

```bash
ls -lh uv.lock
```

Expected: file exists, non-zero size.

**Step 3: Commit**

```bash
git add uv.lock
git commit -m "chore: add uv lockfile for reproducible Docker builds"
```

---

### Task 2: Write the Dockerfile

One image serves all three services (migrate, universe-dl, daily-dl). It installs all runtime dependencies, copies the app code, and sets no default `CMD` — each service defines its own command.

**Files:**
- Create: `Dockerfile`

**Step 1: Create the Dockerfile**

```dockerfile
FROM python:3.12-slim

# git is required by daily-dl (subprocess calls `git diff`)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv from the official distroless image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (cached layer — only re-runs when pyproject.toml/uv.lock change)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy application source
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./
```

**Step 2: Build the image to verify it compiles**

```bash
docker compose build
```

Expected: Build succeeds, image tagged as `bill-retrieval-chatbot-app` (or similar). No errors.

**Step 3: Commit**

```bash
git add Dockerfile
git commit -m "chore: add Dockerfile for ETL pipeline services"
```

---

### Task 3: Update .env.example with new variables

Two new variables tell the ETL services where the data lives on the host. They map to volume mount sources in docker-compose.yml.

**Files:**
- Modify: `.env.example`

**Step 1: Check what's already in .env.example**

```bash
cat .env.example
```

**Step 2: Append the new variables**

Add to the bottom of `.env.example`:

```bash
# --- ETL Pipeline paths (used by docker compose ETL services) ---
# Absolute path on the host to the unzipped BILLSTATUS corpus
CORPUS_DIR=/path/to/congress/data/bills

# Absolute path on the host to the local unitedstates/congress git repo
REPO_PATH=/path/to/congress
```

**Step 3: Commit**

```bash
git add .env.example
git commit -m "chore: add CORPUS_DIR and REPO_PATH to .env.example for ETL services"
```

---

### Task 4: Add ETL services to docker-compose.yml

Three new services, all behind profiles:

| Service | Profile | What it does |
|---------|---------|--------------|
| `migrate` | `etl` | Runs `alembic upgrade head` once, then exits 0 |
| `universe-dl` | `universe-dl` | Bulk ingests corpus; mounts `CORPUS_DIR` read-only |
| `daily-dl` | `daily-dl` | Ingests git diff; mounts `REPO_PATH` read-write (git needs to write) |

`universe-dl` and `daily-dl` both declare `depends_on: migrate: condition: service_completed_successfully` — Compose will run migrations automatically before either pipeline starts.

**Files:**
- Modify: `docker-compose.yml`

**Step 1: Open docker-compose.yml and add the three services**

Replace the entire file with:

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-billchatbot}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-billchatbot_dev_password}
      POSTGRES_DB: ${POSTGRES_DB:-billchatbot}
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-billchatbot}"]
      interval: 5s
      timeout: 5s
      retries: 5

  migrate:
    build: .
    command: uv run alembic upgrade head
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-billchatbot}:${POSTGRES_PASSWORD:-billchatbot_dev_password}@postgres:5432/${POSTGRES_DB:-billchatbot}
    depends_on:
      postgres:
        condition: service_healthy
    restart: "no"
    profiles: [etl, universe-dl, daily-dl]

  universe-dl:
    build: .
    command: uv run python -m app.cli universe-dl /data/corpus
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-billchatbot}:${POSTGRES_PASSWORD:-billchatbot_dev_password}@postgres:5432/${POSTGRES_DB:-billchatbot}
      ETL_BATCH_SIZE: ${ETL_BATCH_SIZE:-100}
    volumes:
      - ${CORPUS_DIR:?Set CORPUS_DIR in .env to the host path of the BILLSTATUS corpus}:/data/corpus:ro
    depends_on:
      postgres:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully
    restart: "no"
    profiles: [universe-dl]

  daily-dl:
    build: .
    command: uv run python -m app.cli daily-dl /data/repo
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-billchatbot}:${POSTGRES_PASSWORD:-billchatbot_dev_password}@postgres:5432/${POSTGRES_DB:-billchatbot}
    volumes:
      - ${REPO_PATH:?Set REPO_PATH in .env to the host path of the congress git repo}:/data/repo
    depends_on:
      postgres:
        condition: service_healthy
      migrate:
        condition: service_completed_successfully
    restart: "no"
    profiles: [daily-dl]

volumes:
  postgres_data:
```

**Step 2: Validate the Compose file**

```bash
docker compose config
```

Expected: Rendered YAML with no errors. Confirm `universe-dl` and `daily-dl` services appear, each with their profile listed.

**Step 3: Verify plain `up` does NOT start ETL services**

```bash
docker compose up --dry-run
```

Expected: Only `postgres` listed. No `migrate`, `universe-dl`, or `daily-dl`.

**Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add migrate, universe-dl, and daily-dl Docker Compose services behind profiles"
```

---

### Task 5: Smoke test migrate service

Confirm the migrate service connects to Postgres and applies migrations cleanly.

**Step 1: Start postgres**

```bash
docker compose up -d postgres
```

Expected: postgres container healthy (check with `docker compose ps`).

**Step 2: Run migrate**

```bash
docker compose --profile etl run --rm migrate
```

Expected output includes:
```
INFO  [alembic.runtime.migration] Running upgrade  -> 21a38ea0e61a, create bill tables
```
Container exits 0.

**Step 3: Run migrate again to confirm idempotency**

```bash
docker compose --profile etl run --rm migrate
```

Expected:
```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
```
No `Running upgrade` line — already at head. Container exits 0.

**Step 4: Tear down**

```bash
docker compose down
```

---

### Task 6: Smoke test universe-dl service

Use the fixture XML from the test suite as a minimal corpus to verify the container ingests without errors.

**Step 1: Set CORPUS_DIR in .env to the test fixtures directory**

In your `.env`:
```
CORPUS_DIR=/absolute/path/to/.worktrees/bill-ingestion-pipelines/tests/ingestion/fixtures
```

**Step 2: Start postgres and run universe-dl**

```bash
docker compose up -d postgres
docker compose --profile universe-dl run --rm universe-dl
```

Expected:
- migrate runs first and exits 0
- universe-dl starts, processes `sample_billstatus.xml`, logs something like:
  ```
  Universe DL complete: {'processed': 1, 'failed': 0, 'skipped': 0}
  ```
- Container exits 0.

**Step 3: Verify the bill landed in the database**

```bash
docker compose exec postgres psql -U billchatbot -d billchatbot -c "SELECT bill_id, title FROM bills;"
```

Expected: One row with `118-hr-1234`.

**Step 4: Tear down**

```bash
docker compose down
```

---

## Running the Pipelines for Real

### Universe DL (one-time bulk load)

```bash
# 1. Set CORPUS_DIR in .env to the unzipped BILLSTATUS corpus path
echo "CORPUS_DIR=/path/to/congress/data/bills" >> .env

# 2. Run (migrations applied automatically before ingest starts)
docker compose --profile universe-dl run --rm universe-dl
```

### Daily DL (incremental updates, run after `usc-run bills`)

```bash
# 1. Set REPO_PATH in .env to the local congress repo
echo "REPO_PATH=/path/to/congress" >> .env

# 2. Run
docker compose --profile daily-dl run --rm daily-dl
```

### Cron (host-level)

```cron
# Daily DL at 02:00 UTC — runs migrations automatically if schema is behind
0 2 * * * cd /path/to/bill-retrieval-chatbot && docker compose --profile daily-dl run --rm daily-dl >> /var/log/daily-dl.log 2>&1
```

---

## Design Notes

- **`:?` variable syntax** in volume mounts (`${CORPUS_DIR:?...}`) causes Compose to fail loudly with a clear error message if the variable is unset, rather than mounting an empty path silently.
- **`profiles` on `migrate`** includes all three ETL profile names (`etl`, `universe-dl`, `daily-dl`). This means `migrate` is activated whenever any of those profiles is active, ensuring it always runs first without needing to be called explicitly.
- **`daily-dl` volume is not `:ro`** because `git diff HEAD@{1} HEAD` may update the reflog/index inside the repo directory.
