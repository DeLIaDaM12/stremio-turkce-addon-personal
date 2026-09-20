import re
import urllib.parse
from typing import Dict, List, Set, Tuple

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
    BASE_URL = "https://dizipalw.com"  # Active mirror

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    REQUEST_TIMEOUT = httpx.Timeout(8.0, connect=5.0)
    MAX_CANDIDATES = 10
    HLS_URL_PATTERN = re.compile(
        r"https?://[^\"'\s<>]+\.m3u8(?:\?[^\"'\s<>]*)?",
        re.IGNORECASE,
    )

    def __init__(self) -> None:
        self.generic_hls = GenericHlsExtractor()
        self.vidmoly = VidmolyExtractor()

    @classmethod
    def _normalize_url(cls, base_url: str, href: str) -> str:
        """Resolve absolute, protocol-relative, and relative URLs safely."""
        if not href:
            return ""

        href = href.strip()
        if href.startswith(("javascript:", "mailto:", "#")):
            return ""
        if href.startswith(("http://", "https://")):
            return href
        if href.startswith("//"):
            return f"https:{href}"
        return urllib.parse.urljoin(f"{base_url.rstrip('/')}/", href)

    @staticmethod
    def _normalized_text(value: str) -> str:
        return " ".join((value or "").casefold().split())

    @classmethod
    def _title_matches(cls, title_text: str, meta: MediaMeta) -> bool:
        """Return true for a title match, or when no useful title data exists."""
        title = cls._normalized_text(title_text)
        candidates = {
            cls._normalized_text(value)
            for value in (meta.original_title, meta.turkish_title)
            if value
        }

        if not candidates:
            return True
        if any(candidate and candidate in title for candidate in candidates):
            return True

        # Search pages frequently omit the title but include the release year.
        if meta.year:
            return any(str(meta.year + offset) in title for offset in (-1, 0, 1))

        return False

    @classmethod
    def _episode_url(cls, base_url: str, meta: MediaMeta) -> str:
        if meta.media_type != "series" or not meta.season or not meta.episode:
            return base_url

        suffix = f"-{meta.season}-sezon-{meta.episode}-bolum"
        normalized = base_url.rstrip("/")
        if normalized.casefold().endswith(suffix.casefold()):
            return f"{normalized}/"
        return f"{normalized}{suffix}/"

    @classmethod
    def _search_candidates(cls, soup: BeautifulSoup, meta: MediaMeta) -> List[str]:
        selectors = (
            "article a, .search-result a, .movies-list a, .film a, "
            ".movie a, a[href*='/film/'], a[href*='/dizi/'], a[href*='/series/']"
        )
        candidates: List[str] = []
        seen: Set[str] = set()

        for node in soup.select(selectors):
            href = node.get("href")
            url = cls._normalize_url(cls.BASE_URL, href or "")
            if not url or url in seen:
                continue

            label = node.get("title") or node.get_text(" ", strip=True)
            if not cls._title_matches(label, meta):
                continue

            seen.add(url)
            candidates.append(cls._episode_url(url, meta))

        return candidates

    @classmethod
    def _extract_hls_urls(cls, html: str, soup: BeautifulSoup, page_url: str) -> List[str]:
        urls: List[str] = []
        seen: Set[str] = set()

        def add(raw_url: str) -> None:
            url = cls._normalize_url(page_url, raw_url)
            if url and ".m3u8" in url.casefold() and url not in seen:
                seen.add(url)
                urls.append(url)

        for match in cls.HLS_URL_PATTERN.findall(html):
            add(match)

        for node in soup.select("iframe, source, script, a, video"):
            for attribute in ("src", "data-src", "data-url", "data-file", "href"):
                value = node.get(attribute)
                if value and ".m3u8" in value.casefold():
                    add(value)

        return urls

    async def _extract_stream(self, source_url: str, referer: str, headers: Dict[str, str]):
        source_lower = source_url.casefold()

        if "vidmoly" in source_lower:
            return await self.vidmoly.extract(source_url, referer=referer)

        if ".m3u8" in source_lower:
            return {
                "url": source_url,
                "quality": "1080p",
                "headers": {
                    "Referer": referer,
                    "User-Agent": headers["User-Agent"],
                },
            }

        return await self.generic_hls.extract(source_url, referer=referer)

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        if not meta.search_queries:
            return []

        request_headers = {
            "User-Agent": self.USER_AGENT,
            "Referer": self.BASE_URL,
        }
        streams: List[Stream] = []
        seen_stream_urls: Set[str] = set()

        async with httpx.AsyncClient(
            headers=request_headers,
            timeout=self.REQUEST_TIMEOUT,
            follow_redirects=True,
            # Keep TLS verification enabled; disable it only for a known broken mirror.
            verify=True,
        ) as client:
            target_url = ""

            for query in meta.search_queries:
                try:
                    search_url = f"{self.BASE_URL}/find"
                    response = await client.get(search_url, params={"q": query})
                    response.raise_for_status()
                except (httpx.HTTPError, ValueError) as exc:
                    print(f"[{self.name}] Search error for '{query}': {exc}")
                    continue

                candidates = self._search_candidates(
                    BeautifulSoup(response.text, "html.parser"), meta
                )
                if not candidates:
                    continue

                # Select the first candidate that actually contains a playable source.
                for candidate in candidates[: self.MAX_CANDIDATES]:
                    try:
                        page_response = await client.get(candidate)
                        if page_response.status_code != 200:
                            continue

                        page_soup = BeautifulSoup(page_response.text, "html.parser")
                        if self._extract_hls_urls(page_response.text, page_soup, candidate):
                            target_url = candidate
                            break
                    except httpx.HTTPError as exc:
                        print(f"[{self.name}] Candidate error for '{candidate}': {exc}")

                if target_url:
                    break

            if not target_url:
                return streams

            try:
                page_response = await client.get(target_url)
                page_response.raise_for_status()
                page_soup = BeautifulSoup(page_response.text, "html.parser")
                source_urls = self._extract_hls_urls(
                    page_response.text, page_soup, target_url
                )

                limit = max(0, config.max_streams_per_provider)
                for source_url in source_urls[:limit or None]:
                    try:
                        extracted = await self._extract_stream(
                            source_url, target_url, request_headers
                        )
                    except Exception as exc:
                        print(f"[{self.name}] Extraction error for '{source_url}': {exc}")
                        continue

                    if not extracted or not extracted.get("url"):
                        continue

                    stream_url = extracted["url"]
                    if stream_url in seen_stream_urls:
                        continue
                    seen_stream_urls.add(stream_url)

                    quality = extracted.get("quality") or "1080p"
                    proxy_headers = extracted.get("headers") or {
                        "Referer": target_url,
                        "User-Agent": self.USER_AGENT,
                    }
                    streams.append(
                        Stream(
                            name=f"[TR DUBLAJ] ⚡ {self.name}",
                            title=(
                                f"{meta.original_title}\n"
                                f"🔊 Türkçe Dublaj | 🎬 {quality} | HLS Stream"
                            ),
                            url=stream_url,
                            behaviorHints=BehaviorHints(proxyHeaders=proxy_headers),
                        )
                    )
            except (httpx.HTTPError, ValueError) as exc:
                print(f"[{self.name}] Stream extraction error: {exc}")

        return streams
