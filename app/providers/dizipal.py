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


class DizipalProvider(BaseProvider):
    name = "Dizipal"
    is_torrent = False
    BASE_URL = "https://dizipal.buzz"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
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

    def _episode_url(self, url: str, meta: MediaMeta) -> str:
        if meta.media_type != "series" or not meta.season or not meta.episode:
            return url
        suffix = f"-sezon-{meta.season}-bolum-{meta.episode}"
        if url.rstrip("/").casefold().endswith(suffix.casefold()):
            return url.rstrip("/") + "/"
        return f"{url.rstrip('/')}{suffix}/"

    def _candidate_urls(self, html: str, meta: MediaMeta) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        selectors = (
            "article a, .search-result a, .movies-list a, .film a, .movie a, "
            "a[href*='/film/'], a[href*='/dizi/'], a[href*='/series/']"
        )
        candidates: List[str] = []
        seen: Set[str] = set()
        for node in soup.select(selectors):
            url = self._normalize_url(self.BASE_URL, node.get("href", ""))
            if not url or url in seen:
                continue
            label = node.get("title") or node.get_text(" ", strip=True)
            if meta.year and not self._title_matches(label, meta):
                continue
            seen.add(url)
            candidates.append(self._episode_url(url, meta))
        return candidates

    def _player_urls(self, html: str, page_url: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        values: List[str] = []
        seen: Set[str] = set()

        def add(value: str) -> None:
            url = self._normalize_url(page_url, value)
            if url and url not in seen:
                seen.add(url)
                values.append(url)

        for node in soup.select(
            "iframe, source, video, a[data-src], a[data-frame], "
            "a[data-url], a[href*='/player/'], script"
        ):
            for attribute in ("src", "data-src", "data-frame", "data-url", "href"):
                value = node.get(attribute)
                if value:
                    add(value)

        # Player URLs are often stored inside JavaScript strings.
        for value in re.findall(r"(?:https?:)?//[^\"'<>\s\\]+", html):
            if any(marker in value.casefold() for marker in ("player", "vidmoly", "rapidrame", "m3u8", "mp4")):
                add(value)

        return values

    async def _extract(self, url: str, referer: str):
        lower = url.casefold()
        if "vidmoly" in lower:
            return await self.vidmoly.extract(url, referer=referer)
        return await self.generic_hls.extract(url, referer=referer)

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        if not meta.search_queries:
            return []

        headers = {"User-Agent": self.USER_AGENT, "Referer": self.BASE_URL}
        streams: List[Stream] = []
        seen_streams: Set[str] = set()

        async with httpx.AsyncClient(
            headers=headers, timeout=8.0, follow_redirects=True, verify=False
        ) as client:
            target_url = ""
            for query in meta.search_queries:
                try:
                    response = await client.get(
                        f"{self.BASE_URL}/find", params={"q": query}
                    )
                    if response.status_code != 200:
                        continue

                    for candidate in self._candidate_urls(response.text, meta)[:10]:
                        try:
                            page = await client.get(candidate)
                            if page.status_code == 200 and self._player_urls(page.text, candidate):
                                target_url = candidate
                                break
                        except httpx.HTTPError as exc:
                            print(f"[{self.name}] Candidate error: {exc}")
                    if target_url:
                        break
                except httpx.HTTPError as exc:
                    print(f"[{self.name}] Search error for '{query}': {exc}")

            if not target_url:
                return []

            try:
                page = await client.get(target_url)
                if page.status_code != 200:
                    return []

                limit = max(0, config.max_streams_per_provider)
                for player_url in self._player_urls(page.text, target_url)[:limit or None]:
                    try:
                        extracted = await self._extract(player_url, target_url)
                    except Exception as exc:
                        print(f"[{self.name}] Extraction error for '{player_url}': {exc}")
                        continue
                    if not extracted or not extracted.get("url"):
                        continue

                    stream_url = extracted["url"]
                    if stream_url in seen_streams:
                        continue
                    seen_streams.add(stream_url)
                    quality = extracted.get("quality") or "1080p"
                    streams.append(
                        Stream(
                            name=f"[TR DUBLAJ] ⚡ {self.name}",
                            title=f"{meta.original_title}\n🔊 Türkçe Dublaj | 🎬 {quality} | HLS Stream",
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
                print(f"[{self.name}] Stream extraction error: {exc}")

        return streams
