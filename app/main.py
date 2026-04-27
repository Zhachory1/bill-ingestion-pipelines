"""FastAPI application entry point.

Routers mounted under /api:
  GET /api/bills/{id}       — bill metadata, sponsors, subjects
  GET /api/bills/{id}/text  — title + summary payload for LLM context
  GET /api/search?q=        — semantic search via pgvector cosine similarity
"""

from fastapi import FastAPI
from app.api import bills, chat, search

app = FastAPI(title="Bill Retrieval API", version="0.1.0")
app.include_router(bills.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
