"""Small in-process request limits for expensive endpoints."""

import time
from collections import defaultdict, deque
from fastapi import HTTPException, Request
from app.config import settings

_requests: dict[str, deque[float]] = defaultdict(deque)


def clear_rate_limits() -> None:
    _requests.clear()


def enforce_rate_limit(request: Request) -> None:
    if settings.ENVIRONMENT == "development" or settings.REQUEST_RATE_LIMIT <= 0:
        return
    client = request.client.host if request.client else "unknown"
    now = time.time()
    window_start = now - settings.REQUEST_RATE_WINDOW_SECONDS
    hits = _requests[client]
    while hits and hits[0] <= window_start:
        hits.popleft()
    if len(hits) >= settings.REQUEST_RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")
    hits.append(now)
