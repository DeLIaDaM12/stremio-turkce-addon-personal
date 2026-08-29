import time
from typing import Any, Optional
from cachetools import TTLCache
from app.config import settings

# In-memory TTL caches
metadata_cache = TTLCache(maxsize=2000, ttl=settings.METADATA_CACHE_TTL)
streams_cache = TTLCache(maxsize=1000, ttl=settings.STREAMS_CACHE_TTL)

class CacheService:
    @staticmethod
    def get(cache: TTLCache, key: str) -> Optional[Any]:
        return cache.get(key)

    @staticmethod
    def set(cache: TTLCache, key: str, value: Any) -> None:
        cache[key] = value

    @staticmethod
    def generate_key(*args) -> str:
        return ":".join(str(arg) for arg in args)
