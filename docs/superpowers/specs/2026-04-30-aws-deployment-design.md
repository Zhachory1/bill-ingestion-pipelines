# AWS Deployment Design — bill-retrieval-chatbot

**Date:** 2026-04-30
**Status:** Approved

## Overview

Deploy bill-retrieval-chatbot publicly on AWS using single EC2 instance running Docker Compose. Personal/demo scale. Cost-optimized (~$15–25/month on-demand; ~$10–18/month with 1-year Reserved Instance). No auth — users supply own Anthropic API keys.

## Infrastructure

**EC2:** t3.small (2 vCPU, 2GB RAM), us-east-1, Amazon Linux 2023.

**Storage (EBS):**
- Root: 20GB gp3 (OS + Docker images)
- Data volume: 50GB gp3, mounted at `/data`
  - `/data/postgres/` — Postgres data dir (bind-mounted into container — see Application Stack)
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

Docker Compose orchestrates all services on the EC2 instance. The existing `docker-compose.yml` must be extended with two new services: `web` and `nginx`. These do not exist yet.

**Services:**

| Service | Image | Role |
|---------|-------|------|
| `postgres` | pgvector/pgvector:pg16 | DB (existing) |
| `web` | local build | FastAPI app + static files |
| `nginx` | nginx:alpine (with Certbot) | TLS termination, reverse proxy → `web:8000` |

All persistent services use `restart: unless-stopped` for auto-restart on reboot.

### `web` service (to add to docker-compose.yml)

```yaml
web:
  build: .
  command: uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
  expose:
    - "8000"
  environment:
    DATABASE_URL: postgresql://${POSTGRES_USER:-billchatbot}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB:-billchatbot}
    ENVIRONMENT: production
    RELOAD: "false"
    LLM_PROVIDER: ${LLM_PROVIDER:-anthropic}
    EMBEDDING_MODEL: ${EMBEDDING_MODEL:-all-MiniLM-L6-v2}
    LOG_LEVEL: ${LOG_LEVEL:-INFO}
  depends_on:
    postgres:
      condition: service_healthy
  restart: unless-stopped
```

Also add `CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]` to the Dockerfile so the image runs correctly standalone (not only via compose).

### `nginx` service (to add to docker-compose.yml)

Use the `nginx:alpine` image with a bind-mounted config and a separate `certbot/certbot` container sharing the Let's Encrypt volume. Follow the [official Certbot + nginx Docker pattern](https://certbot.eff.org/instructions?system=docker). Two shared volumes:
- `./nginx/conf/` — nginx config files (proxy_pass to `web:8000`)
- `./certbot/` — Let's Encrypt certificates and webroot challenge

Initial cert issuance uses HTTP challenge on port 80; nginx config switches to HTTPS after cert is obtained. Certificate auto-renewal via a cron job that runs `docker compose run --rm certbot renew`.

Minimal nginx config (`nginx/conf/app.conf`) for HTTPS:
```nginx
server {
    listen 80;
    server_name yourdomain.com;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}
server {
    listen 443 ssl;
    server_name yourdomain.com;
    ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
    location / {
        proxy_pass http://web:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Postgres storage: bind mount (not named volume)

Change the existing `postgres` service to use a bind mount so data lives at a known path on the EBS volume (easier snapshots, no Docker volume internals):

```yaml
postgres:
  volumes:
    - /data/postgres:/var/lib/postgresql/data  # bind mount to EBS
```

Remove the `postgres_data` named volume from the `volumes:` section.

### Dockerfile fix required

Add `COPY static/ ./static/` to the Dockerfile before the app starts. Without this, static files are absent from the container and the frontend returns 404:

```dockerfile
COPY static/ ./static/      # add this line
```

This must be done before first deploy.

## ETL Pipeline

### Initial bulk load (one-time)

The `universe-dl` profile automatically runs `migrate` first via `depends_on`. No need to run migrate separately:

```bash
# Run in tmux/screen — this triggers migrate automatically, then ingests all bills
CORPUS_DIR=/data/corpus docker compose --profile universe-dl run --rm universe-dl
```

The BILLSTATUS corpus must be downloaded and extracted to the host (e.g., `/data/corpus`) before running this command.

### Daily sync (ongoing)

Linux crontab entry. Must source `.env` explicitly since cron does not inherit shell environment:

```
0 3 * * * set -a && source /app/.env && set +a && docker compose -f /app/docker-compose.yml --profile daily-dl run --rm daily-dl >> /var/log/daily-dl.log 2>&1
```

The `daily-dl` service requires `REPO_PATH` (pointing to `/data/congress`) to be set — it will hard-fail with an error if unset.

## Production `.env` on EC2

```
ENVIRONMENT=production
RELOAD=false

# Database
POSTGRES_USER=billchatbot
POSTGRES_PASSWORD=<strong-random-password>
POSTGRES_DB=billchatbot
DATABASE_URL=postgresql://billchatbot:<password>@postgres:5432/billchatbot

# LLM — users provide their own key at runtime; no server-side key needed
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=2000

# Data APIs
CONGRESS_GOV_API_KEY=<key>
GOVTRACK_API_KEY=<key>

# Retrieval
EMBEDDING_MODEL=all-MiniLM-L6-v2
DEFAULT_RETRIEVAL_STRATEGY=semantic
MAX_RESULTS=10

# ETL paths (used by ETL compose profiles)
CORPUS_DIR=/data/corpus
REPO_PATH=/data/congress

# Logging
LOG_LEVEL=INFO
```

## Deployment Process

### Prerequisites (do before launch)

- [ ] Add `COPY static/ ./static/` and `CMD` to Dockerfile
- [ ] Add `web` service to docker-compose.yml
- [ ] Add `nginx` service + certbot to docker-compose.yml
- [ ] Change postgres volume to bind mount at `/data/postgres`
- [ ] Create `nginx/conf/` directory with nginx config files

### One-time Setup on EC2

1. Launch EC2 t3.small, attach 50GB EBS volume
2. Format and mount EBS: `mkfs.ext4 /dev/xvdf && mount /dev/xvdf /data && echo '/dev/xvdf /data ext4 defaults 0 2' >> /etc/fstab`
3. Create data dirs: `mkdir -p /data/postgres /data/congress /data/corpus`
4. Install Docker Engine + Docker Compose plugin
5. `git clone <this-repo> /app && cd /app`
6. Create `/app/.env` with production values (see above)
7. Clone congress repo: `git clone https://github.com/unitedstates/congress /data/congress`
8. Point domain DNS → Elastic IP; wait for propagation
9. Obtain TLS cert (HTTP challenge): follow Certbot + nginx Docker pattern
10. `docker compose up -d` — starts postgres, web, nginx
11. Run bulk ingest (in tmux — takes hours): `CORPUS_DIR=/data/corpus docker compose --profile universe-dl run --rm universe-dl`
12. Add crontab entry for daily sync (see ETL section above)

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

| Resource | Monthly Cost (on-demand) |
|----------|--------------------------|
| EC2 t3.small us-east-1 | ~$15 |
| EBS gp3 70GB total | ~$6 |
| Elastic IP (attached) | $0 |
| Data transfer | ~$1 |
| **Total** | **~$22/month** |

A 1-year Reserved Instance for t3.small cuts EC2 cost to ~$9/month (~$15/month total).

## Backups

Postgres data lives on the EBS bind mount at `/data/postgres`. Take an AWS EBS snapshot periodically via the console or AWS CLI:
```bash
aws ec2 create-snapshot --volume-id vol-xxxx --description "billchatbot-$(date +%F)"
```

## Out of Scope

- High availability / multi-AZ
- Auto-scaling
- CI/CD pipeline (manual git pull deploys)
- Monitoring / alerting
- User authentication
