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
        streams = await asyncio.wait_for(
            provider.get_streams(meta, config), timeout=PROVIDER_TIMEOUT
        )
        if not isinstance(streams, list):
            print(f"[ProviderAggregator] {name}: invalid result type {type(streams).__name__}")
            return []
        print(f"[ProviderAggregator] {name}: {len(streams)} stream(s)")
        return streams
    except asyncio.TimeoutError:
        print(f"[ProviderAggregator] {name}: timeout after {PROVIDER_TIMEOUT:.0f}s")
    except Exception as exc:
        print(f"[ProviderAggregator] {name}: failed: {type(exc).__name__}: {exc}")
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
        print(f"[ProviderAggregator] cache hit: {len(cached)} stream(s)")
        return cached

    tasks = []
    enabled = set(config.enabled_providers)
    print(
        f"[ProviderAggregator] request title={meta.original_title!r} "
        f"type={meta.media_type} queries={meta.search_queries!r} enabled={sorted(enabled)}"
    )

    for name, provider in ALL_PROVIDERS.items():
        if name not in enabled:
            print(f"[ProviderAggregator] {name}: disabled")
            continue
        if provider.is_torrent and not config.enable_torrents:
            print(f"[ProviderAggregator] {name}: torrents disabled")
            continue
        if not provider.is_torrent and not config.enable_direct:
            print(f"[ProviderAggregator] {name}: direct sources disabled")
            continue
        tasks.append(_fetch_provider(name, provider, meta, config))

    results = await asyncio.gather(*tasks)
    all_streams: List[Stream] = []
    seen_keys = set()

    for result in results:
        for stream in result:
            key = stream.infoHash or stream.url
            if not key or key in seen_keys:
                continue
            seen_keys.add(key)
            all_streams.append(stream)

    all_streams.sort(key=_stream_score, reverse=True)
    print(f"[ProviderAggregator] total unique streams: {len(all_streams)}")
    if all_streams:
        CacheService.set(streams_cache, cache_key, all_streams)
    return all_streams
