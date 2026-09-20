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
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
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
            "iframe, embed, video, source, script, a[data-src], a[data-frame], "
            "a[data-url], a[href*='/player/'], a[href*='embed']"
        ):
            for attribute in ("src", "data-src", "data-frame", "data-url", "href"):
                value = node.get(attribute)
                if value:
                    add(value)

        for value in re.findall(r"(?:https?:)?//[^\"'<>\s\\]+", html):
            lower = value.casefold()
            if any(marker in lower for marker in ("player", "embed", "vidmoly", "rapidrame", ".m3u8", ".mp4")):
                add(value)

        for value in re.findall(
            r"(?:file|src|source|url|playlist|hls|stream)\s*[:=]\s*[\"']([^\"']+)",
            html,
            re.IGNORECASE,
        ):
            add(value)
        return urls

    @staticmethod
    def _diagnostic(response: httpx.Response) -> str:
        title = BeautifulSoup(response.text, "html.parser").title
        page_title = title.get_text(" ", strip=True) if title else ""
        return f"status={response.status_code} url={response.url} bytes={len(response.content)} title={page_title!r}"

    async def _extract(self, url: str, referer: str):
        if "vidmoly" in url.casefold():
            return await self.vidmoly.extract(url, referer=referer)
        return await self.generic_hls.extract(url, referer=referer)

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        if meta.media_type != "movie":
            return []

        headers = {"User-Agent": self.USER_AGENT, "Referer": self.BASE_URL}
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
                        f"{self.BASE_URL}/arama/{urllib.parse.quote(query)}"
                    )
                    print(f"[{self.name}] search {self._diagnostic(response)} query={query!r}")
                    if response.status_code != 200:
                        continue

                    soup = BeautifulSoup(response.text, "html.parser")
                    candidates: List[str] = []
                    seen_candidates: Set[str] = set()
                    for node in soup.select(
                        ".film-list a, .film-item a, a.film-link, .movie a, "
                        ".card a, .item a, article a, a[rel='bookmark']"
                    ):
                        candidate = self._normalize_url(self.BASE_URL, node.get("href", ""))
                        if not candidate or candidate in seen_candidates:
                            continue
                        label = node.get("title") or node.get_text(" ", strip=True)
                        if meta.year and not self._title_matches(label, meta):
                            continue
                        seen_candidates.add(candidate)
                        candidates.append(candidate)

                    print(f"[{self.name}] candidates={len(candidates)}")
                    for candidate in candidates[:10]:
                        page = await client.get(candidate)
                        players = self._player_urls(page.text, candidate) if page.status_code == 200 else []
                        print(f"[{self.name}] candidate {self._diagnostic(page)} players={len(players)}")
                        if players:
                            target_url = candidate
                            break
                    if target_url:
                        break
                except httpx.HTTPError as exc:
                    print(f"[{self.name}] search error query={query!r}: {exc}")

            if not target_url:
                print(f"[{self.name}] no playable target found")
                return streams

            try:
                page = await client.get(target_url)
                if page.status_code != 200:
                    print(f"[{self.name}] target rejected {self._diagnostic(page)}")
                    return streams

                player_urls = self._player_urls(page.text, target_url)
                print(f"[{self.name}] target players={len(player_urls)} url={target_url}")
                limit = max(0, config.max_streams_per_provider)
                for player_url in player_urls[:limit or None]:
                    try:
                        extracted = await self._extract(player_url, target_url)
                    except Exception as exc:
                        print(f"[{self.name}] extraction error url={player_url}: {type(exc).__name__}: {exc}")
                        continue
                    if not extracted or not extracted.get("url"):
                        print(f"[{self.name}] extractor returned no media url={player_url}")
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
                print(f"[{self.name}] target request error: {exc}")

        print(f"[{self.name}] returning {len(streams)} stream(s)")
        return streams
