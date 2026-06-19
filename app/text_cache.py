"""Small in-process cache for expensive govinfo full-text fetches."""

from collections import OrderedDict
from collections.abc import Callable

from app.config import settings

_cache: OrderedDict[str, str] = OrderedDict()


def get_cached_text(key: str, fetcher: Callable[[str], str]) -> str:
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]

    text = fetcher(key)
    _cache[key] = text
    _cache.move_to_end(key)
    while len(_cache) > settings.FULLTEXT_CACHE_MAX_ENTRIES:
        _cache.popitem(last=False)
    return text


def clear_text_cache() -> None:
    _cache.clear()


def truncate_text(text: str, max_chars: int | None = None) -> str:
    limit = max_chars if max_chars is not None else settings.MAX_BILL_TEXT_CHARS
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n[Truncated to fit chat context limit.]"
