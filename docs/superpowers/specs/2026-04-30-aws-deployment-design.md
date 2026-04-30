# AWS Deployment Design — bill-retrieval-chatbot

**Date:** 2026-04-30
**Status:** Approved

## Overview

Deploy bill-retrieval-chatbot publicly on AWS using single EC2 instance running Docker Compose. Personal/demo scale. Cost-optimized (~$15–25/month). No auth — users supply own Anthropic API keys.

## Infrastructure

**EC2:** t3.small (2 vCPU, 2GB RAM), us-east-1, Amazon Linux 2023.

**Storage (EBS):**
- Root: 20GB gp3 (OS + Docker images)
- Data volume: 30–50GB gp3, mounted at `/data`
  - `/data/postgres/` — Postgres data dir
  - `/data/congress/` — unitedstates/congress git repo (daily ETL input)

**Networking:**
- Default VPC
- Elastic IP (prevents DNS churn on restart)
- Security group inbound rules:
  - Port 80 (HTTP) — 0.0.0.0/0
  - Port 443 (HTTPS) — 0.0.0.0/0
  - Port 22 (SSH) — your IP only

**DNS:** Domain/subdomain pointed at Elastic IP. Required for Let's Encrypt TLS.

## Application Stack

Docker Compose orchestrates all services on the EC2 instance.

**Services:**
| Service | Image | Role |
|---------|-------|------|
| `postgres` | pgvector/pgvector:pg16 | DB (existing) |
| `web` | local build | FastAPI app + static files |
| `nginx` | nginx:alpine + Certbot | TLS termination, reverse proxy → port 8000 |

All services use `restart: unless-stopped` for auto-restart on reboot.

**Dockerfile fix needed:** add `COPY static/ ./static/` — currently missing, so static files won't be found in container.

**Environment (`.env` on EC2):**
```
ENVIRONMENT=production
RELOAD=false
POSTGRES_PASSWORD=<strong-random-password>
DATABASE_URL=postgresql://billchatbot:<password>@postgres:5432/billchatbot
ANTHROPIC_API_KEY=          # empty — users provide their own
CONGRESS_GOV_API_KEY=<key>
LOG_LEVEL=INFO
```

## ETL Pipeline

**Initial bulk load (one-time):**
```bash
docker compose --profile etl run --rm migrate
docker compose --profile universe-dl run --rm universe-dl
```
Requires `CORPUS_DIR` env var pointing to unzipped BILLSTATUS corpus on the host (can be temporarily attached EBS or downloaded directly to EC2).

**Daily sync (ongoing):**
Linux crontab entry:
```
0 3 * * * cd /app && docker compose --profile daily-dl run --rm daily-dl >> /var/log/daily-dl.log 2>&1
```
Reads from `/data/congress` (congress git repo, pulled before each run or auto-pulled inside container).

## Deployment Process

### One-time Setup

1. Launch EC2 t3.small, attach + format + mount EBS data volume at `/data`
2. Install Docker Engine + Docker Compose plugin
3. `git clone` this repo to `/app` on EC2
4. `git clone https://github.com/unitedstates/congress /data/congress`
5. Create `/app/.env` with production values
6. Point domain DNS → Elastic IP, wait for propagation
7. `docker compose up -d` — starts postgres, web, nginx
8. Run migrations: `docker compose --profile etl run --rm migrate`
9. Run bulk ingest (long-running, run in tmux/screen):
   `docker compose --profile universe-dl run --rm universe-dl`
10. Add crontab for daily sync

### Code Updates

```bash
cd /app && git pull
docker compose build web
docker compose up -d web
```

### Database Migrations

```bash
docker compose --profile etl run --rm migrate
```

## Cost Estimate

| Resource | Monthly Cost |
|----------|-------------|
| EC2 t3.small (us-east-1) | ~$15 |
| EBS gp3 70GB total | ~$6 |
| Elastic IP | ~$0 (attached) |
| Data transfer | ~$1 |
| **Total** | **~$22/month** |

## Out of Scope

- High availability / multi-AZ
- Auto-scaling
- CI/CD pipeline (manual git pull deploys)
- Monitoring / alerting (CloudWatch not configured)
- User authentication
