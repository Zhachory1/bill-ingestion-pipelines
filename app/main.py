"""FastAPI application entry point.

Routers mounted under /api:
  GET /api/bills/{id}       — bill metadata, sponsors, subjects
  GET /api/bills/{id}/text  — title + summary payload for LLM context
  GET /api/search?q=        — semantic search via pgvector cosine similarity
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.api import bills, chat, search
from app.rate_limit import limiter

app = FastAPI(title="Bill Retrieval API", version="0.1.0")

# Add rate limit exception handler
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.include_router(bills.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.mount("/", StaticFiles(directory="static", html=True), name="static")
