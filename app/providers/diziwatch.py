import re
import urllib.parse
from typing import List, Set

import httpx
from bs4 import BeautifulSoup

from app.extractors.generic_hls import GenericHlsExtractor
from app.models import BehaviorHints, Stream, UserConfig
from app.providers.base import BaseProvider
from app.services.metadata import MediaMeta


class DiziWatchProvider(BaseProvider):
    name = "DiziWatch"
    is_torrent = False
    BASE_URL = "https://diziwatch.net"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self) -> None:
        self.generic_hls = GenericHlsExtractor()

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
        names = [
            value.casefold()
            for value in (meta.original_title, meta.turkish_title)
            if value
        ]
        if not names:
            return True
        if any(name in title for name in names):
            return True
        return bool(
            meta.year
            and any(str(meta.year + offset) in title for offset in (-1, 0, 1))
        )

    def _episode_url(self, series_url: str, meta: MediaMeta) -> str:
        base = series_url.rstrip("/")
        suffix = f"-{meta.season}-sezon-{meta.episode}-bolum-izle"
        if base.casefold().endswith(suffix.casefold()):
            return base + "/"
        return f"{base}{suffix}/"

    def _candidate_urls(self, html: str, meta: MediaMeta) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        selectors = (
            ".post-content a, .entry-title a, article a, .title a, "
            ".post a, .item a, a[rel='bookmark']"
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
        urls: List[str] = []
        seen: Set[str] = set()

        def add(value: str) -> None:
            url = self._normalize_url(page_url, value)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        for node in soup.select(
            "iframe, source, video, script, a[data-src], a[data-frame], "
            "a[data-url], a[href*='/player/'], a[href*='embed']"
        ):
            for attribute in (
                "src",
                "data-src",
                "data-frame",
                "data-url",
                "href",
            ):
                value = node.get(attribute)
                if value:
                    add(value)

        # Also inspect common JavaScript player values and direct media URLs.
        for value in re.findall(
            r"(?:https?:)?//[^\"'<>\s\\]+",
            html,
            flags=re.IGNORECASE,
        ):
            lower = value.casefold()
            if any(
                marker in lower
                for marker in ("player", "embed", "m3u8", "mp4", "vidmoly", "rapidrame")
            ):
                add(value)

        return urls

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        if meta.media_type != "series" or not meta.season or not meta.episode:
            return []

        headers = {
            "User-Agent": self.USER_AGENT,
            "Referer": self.BASE_URL,
        }
        streams: List[Stream] = []
        seen_streams: Set[str] = set()

        async with httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(8.0, connect=5.0),
            follow_redirects=True,
            verify=False,
        ) as client:
            target_url = ""

            for query in meta.search_queries:
                try:
                    response = await client.get(
                        self.BASE_URL,
                        params={"s": query},
                    )
                    if response.status_code != 200:
                        continue

                    candidates = self._candidate_urls(response.text, meta)
                    for candidate in candidates[:10]:
                        try:
                            page = await client.get(candidate)
                            if page.status_code != 200:
                                continue
                            if self._player_urls(page.text, candidate):
                                target_url = candidate
                                break
                        except httpx.HTTPError as exc:
                            print(
                                f"[{self.name}] Candidate error for "
                                f"'{candidate}': {exc}"
                            )

                    if target_url:
                        break
                except httpx.HTTPError as exc:
                    print(f"[{self.name}] Search error for '{query}': {exc}")

            if not target_url:
                return streams

            try:
                page = await client.get(target_url)
                if page.status_code != 200:
                    return streams

                limit = max(0, config.max_streams_per_provider)
                player_urls = self._player_urls(page.text, target_url)

                for player_url in player_urls[: limit or None]:
                    try:
                        extracted = await self.generic_hls.extract(
                            player_url,
                            referer=target_url,
                        )
                    except Exception as exc:
                        print(
                            f"[{self.name}] Extraction error for "
                            f"'{player_url}': {exc}"
                        )
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
                            name=f"[TR DUBLAJ/ALT] ⚡ {self.name}",
                            title=(
                                f"{meta.original_title} "
                                f"S{meta.season:02d}E{meta.episode:02d}\n"
                                f"🔊 Türkçe Ses / Altyazı | 🎬 {quality}"
                            ),
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
