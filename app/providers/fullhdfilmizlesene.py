import re
import urllib.parse
from typing import List, Set

import httpx
from bs4 import BeautifulSoup

from app.extractors.generic_hls import GenericHlsExtractor
from app.extractors.vidmoly import VidmolyExtractor
from app.models import BehaviorHints, Stream, UserConfig
from app.providers.base import BaseProvider
from app.services.metadata import MediaMeta


class FullHdFilmizleseneProvider(BaseProvider):
    name = "FullHDFilmizlesene"
    is_torrent = False
    BASE_URL = "https://www.fullhdfilmizlesene.pw"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self) -> None:
        self.generic_hls = GenericHlsExtractor()
        self.vidmoly = VidmolyExtractor()

    @staticmethod
    def _normalize_url(base_url: str, value: str) -> str:
        if not value:
            return ""
        value = value.strip().replace("\\/", "/")
        if value.startswith(("javascript:", "mailto:", "#")):
            return ""
        if value.startswith("//"):
            return "https:" + value
        return urllib.parse.urljoin(base_url.rstrip("/") + "/", value)

    @staticmethod
    def _title_matches(text: str, meta: MediaMeta) -> bool:
        if not text:
            return True
        title = text.casefold()
        names = [value.casefold() for value in (meta.original_title, meta.turkish_title) if value]
        if not names:
            return True
        if any(name in title for name in names):
            return True
        return bool(meta.year and any(str(meta.year + offset) in title for offset in (-1, 0, 1)))

    def _extract_player_urls(self, html: str, base_url: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        urls: List[str] = []
        seen: Set[str] = set()

        def add(value: str) -> None:
            url = self._normalize_url(base_url, value)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        for node in soup.select("iframe, source, script, a[data-frame], a[data-src], a[href*='.m3u8']"):
            for attribute in ("src", "data-src", "data-frame", "href"):
                value = node.get(attribute)
                if value:
                    add(value)

        for match in re.findall(r"(?:https?:)?//[^\"'<>\s\\]+\.(?:m3u8|mp4)(?:\?[^\"'<>\s\\]*)?", html, re.I):
            add(match)

        for match in re.findall(r"(?:src|file|source|url)\s*[:=]\s*[\"']([^\"']+)", html, re.I):
            add(match)

        return urls

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        if meta.media_type != "movie":
            return []

        headers = {"User-Agent": self.USER_AGENT, "Referer": self.BASE_URL}
        streams: List[Stream] = []
        seen_streams: Set[str] = set()

        async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True, verify=False) as client:
            target_url = ""
            for query in meta.search_queries:
                try:
                    response = await client.get(f"{self.BASE_URL}/arama/{urllib.parse.quote(query)}")
                    if response.status_code != 200:
                        continue

                    soup = BeautifulSoup(response.text, "html.parser")
                    for node in soup.select(".film-list a, .film-item a, a.film-link, .movie a, article a"):
                        href = node.get("href")
                        if not href:
                            continue
                        candidate = self._normalize_url(self.BASE_URL, href)
                        if not candidate:
                            continue
                        label = node.get("title") or node.get_text(" ", strip=True)
                        if meta.year and not self._title_matches(label, meta):
                            continue
                        target_url = candidate
                        break
                    if target_url:
                        break
                except httpx.HTTPError as exc:
                    print(f"[{self.name}] Search error: {exc}")

            if not target_url:
                return streams

            try:
                page = await client.get(target_url)
                if page.status_code != 200:
                    return streams

                limit = max(0, config.max_streams_per_provider)
                for player_url in self._extract_player_urls(page.text, target_url)[:limit or None]:
                    try:
                        extracted = None
                        if "vidmoly" in player_url.casefold():
                            extracted = await self.vidmoly.extract(player_url, referer=target_url)
                        else:
                            extracted = await self.generic_hls.extract(player_url, referer=target_url)
                    except Exception as exc:
                        print(f"[{self.name}] Extractor error for '{player_url}': {exc}")
                        continue

                    if not extracted or not extracted.get("url"):
                        continue
                    stream_url = extracted["url"]
                    if stream_url in seen_streams:
                        continue
                    seen_streams.add(stream_url)
                    streams.append(
                        Stream(
                            name=f"[TR DUBLAJ] ⚡ {self.name}",
                            title=f"{meta.original_title}\n🔊 Türkçe Dublaj | 🎬 {extracted.get('quality', '1080p')} | HLS Stream",
                            url=stream_url,
                            behaviorHints=BehaviorHints(
                                proxyHeaders=extracted.get("headers") or {
                                    "Referer": target_url,
                                    "User-Agent": self.USER_AGENT,
                                }
                            ),
                        )
                    )
            except httpx.HTTPError as exc:
                print(f"[{self.name}] Stream request error: {exc}")

        return streams
