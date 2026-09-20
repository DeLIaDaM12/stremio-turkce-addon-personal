import asyncio
from typing import List

from app.models import Stream, UserConfig
from app.services.cache import CacheService, streams_cache
from app.services.metadata import MediaMeta
from app.providers.dizipal import DizipalProvider
from app.providers.diziwatch import DiziWatchProvider
from app.providers.fullhdfilmizlesene import FullHdFilmizleseneProvider
from app.providers.hdfilmcehennemi import HdFilmCehennemiProvider
from app.providers.turktorrent import TurkTorrentProvider

ALL_PROVIDERS = {
    "hdfilmcehennemi": HdFilmCehennemiProvider(),
    "dizipal": DizipalProvider(),
    "fullhdfilmizlesene": FullHdFilmizleseneProvider(),
    "diziwatch": DiziWatchProvider(),
    "turktorrent": TurkTorrentProvider(),
}

PROVIDER_TIMEOUT = 20.0


async def _fetch_provider(name: str, provider, meta: MediaMeta, config: UserConfig) -> List[Stream]:
    try:
        streams = await asyncio.wait_for(provider.get_streams(meta, config), timeout=PROVIDER_TIMEOUT)
        print(f"[ProviderAggregator] {name}: {len(streams)} stream(s)")
        return streams if isinstance(streams, list) else []
    except asyncio.TimeoutError:
        print(f"[ProviderAggregator] {name} timed out")
    except Exception as exc:
        print(f"[ProviderAggregator] {name} failed: {exc}")
    return []


def _stream_score(stream: Stream) -> int:
    text = f"{stream.name} {stream.title}".casefold()
    score = 0
    if "dublaj" in text or "dual" in text:
        score += 100
    if "⚡" in stream.name or stream.url:
        score += 50
    if "2160p" in text or "4k" in text:
        score += 20
    elif "1080p" in text:
        score += 15
    elif "720p" in text:
        score += 5
    return score


async def fetch_all_streams(meta: MediaMeta, config: UserConfig) -> List[Stream]:
    cache_key = CacheService.generate_key(
        "streams", meta.imdb_id, meta.season or 0, meta.episode or 0
    )
    cached = CacheService.get(streams_cache, cache_key)
    if cached:
        return cached

    tasks = []
    for name, provider in ALL_PROVIDERS.items():
        if name not in config.enabled_providers:
            continue
        if provider.is_torrent and not config.enable_torrents:
            continue
        if not provider.is_torrent and not config.enable_direct:
            continue
        tasks.append(_fetch_provider(name, provider, meta, config))

    results = await asyncio.gather(*tasks)
    all_streams: List[Stream] = []
    seen_urls = set()
    seen_hashes = set()

    for result in results:
        for stream in result:
            key = getattr(stream, "infoHash", None) or getattr(stream, "url", None)
            if not key or key in seen_urls or key in seen_hashes:
                continue
            if getattr(stream, "infoHash", None):
                seen_hashes.add(key)
            else:
                seen_urls.add(key)
            all_streams.append(stream)

    all_streams.sort(key=_stream_score, reverse=True)
    if all_streams:
        CacheService.set(streams_cache, cache_key, all_streams)
    return all_streams
