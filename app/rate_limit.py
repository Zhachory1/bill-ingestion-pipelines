"""Rate limiting configuration for the API."""

from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import settings

# Initialize rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    enabled=settings.RATE_LIMIT_ENABLED,
    headers_enabled=True,  # Add X-RateLimit-* headers
)
