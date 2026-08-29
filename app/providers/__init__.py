import asyncio
from typing import List
from app.models import Stream, UserConfig
from app.services.metadata import MediaMeta
from app.services.cache import CacheService, streams_cache
from app.providers.hdfilmcehennemi import HdFilmCehennemiProvider
from app.providers.dizipal import DizipalProvider
from app.providers.fullhdfilmizlesene import FullHdFilmizleseneProvider
from app.providers.diziwatch import DiziWatchProvider
from app.providers.turktorrent import TurkTorrentProvider

ALL_PROVIDERS = {
    "hdfilmcehennemi": HdFilmCehennemiProvider(),
    "dizipal": DizipalProvider(),
    "fullhdfilmizlesene": FullHdFilmizleseneProvider(),
    "diziwatch": DiziWatchProvider(),
    "turktorrent": TurkTorrentProvider(),
}

async def fetch_all_streams(meta: MediaMeta, config: UserConfig) -> List[Stream]:
    """Fetches streams from all enabled providers concurrently."""
    cache_key = CacheService.generate_key("streams", meta.imdb_id, meta.season or 0, meta.episode or 0)
    cached = CacheService.get(streams_cache, cache_key)
    if cached:
        return cached

    tasks = []
    for prov_name, provider in ALL_PROVIDERS.items():
        if prov_name in config.enabled_providers:
            if provider.is_torrent and not config.enable_torrents:
                continue
            if not provider.is_torrent and not config.enable_direct:
                continue
            tasks.append(provider.get_streams(meta, config))

    # Execute all scrapers in parallel with timeout
    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_streams: List[Stream] = []

    for res in results:
        if isinstance(res, list):
            all_streams.extend(res)
        elif isinstance(res, Exception):
            print(f"[ProviderAggregator] Exception occurred: {res}")

    # Prioritize streams: Dubbed Direct Streams first, then Torrent Dual, then Subbed
    def stream_sort_key(s: Stream):
        score = 0
        name_lower = s.name.lower()
        title_lower = s.title.lower()
        
        # Dubbed gets highest priority
        if "dublaj" in name_lower or "dublaj" in title_lower or "dual" in title_lower:
            score += 100
        # Direct streams are faster for TV
        if "⚡" in s.name or s.url:
            score += 50
        # 1080p / 4K quality priority
        if "4k" in name_lower or "2160p" in title_lower:
            score += 20
        elif "1080p" in name_lower or "1080p" in title_lower:
            score += 15
        elif "720p" in name_lower:
            score += 5

        return -score

    all_streams.sort(key=stream_sort_key)

    # Cache successful results
    if all_streams:
        CacheService.set(streams_cache, cache_key, all_streams)

    return all_streams
