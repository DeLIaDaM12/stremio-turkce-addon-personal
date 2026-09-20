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
    def _slug(value: str) -> str:
        value = value.casefold().replace("&", " and ")
        return re.sub(r"[^a-z0-9]+", "-", value).strip("-")

    def _direct_title_urls(self, meta: MediaMeta) -> List[str]:
        urls: List[str] = []
        seen: Set[str] = set()
        for title in (meta.original_title, meta.turkish_title):
            if not title:
                continue
            slug = self._slug(title)
            if not slug:
                continue
            base = f"{self.BASE_URL}/{slug}"
            if meta.media_type == "series" and meta.season and meta.episode:
                variants = (
                    f"{base}-{meta.season}-sezon-{meta.episode}-bolum",
                    f"{base}-sezon-{meta.season}-bolum-{meta.episode}",
                )
            else:
                variants = (base,)
            for value in variants:
                url = value + "/"
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
        return urls

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
        suffixes = (
            f"-{meta.season}-sezon-{meta.episode}-bolum",
            f"-sezon-{meta.season}-bolum-{meta.episode}",
        )
        base = url.rstrip("/")
        if any(base.casefold().endswith(suffix.casefold()) for suffix in suffixes):
            return base + "/"
        return f"{base}-{meta.season}-sezon-{meta.episode}-bolum/"

    def _candidate_urls(self, html: str, meta: MediaMeta) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        candidates: List[str] = []
        seen: Set[str] = set()
        for node in soup.select(
            "article a, .search-result a, .movies-list a, .film a, .movie a, "
            ".poster a, .card a, .item a, a[rel='bookmark'], "
            "a[href*='/film/'], a[href*='/dizi/'], a[href*='/series/']"
        ):
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
            "iframe, source, video, embed, script, a[data-src], a[data-frame], "
            "a[data-url], a[href*='/player/'], a[href*='embed']"
        ):
            for attribute in ("src", "data-src", "data-frame", "data-url", "href"):
                value = node.get(attribute)
                if value:
                    add(value)
        for value in re.findall(r"(?:https?:)?//[^\"'<>\s\\]+", html):
            if any(marker in value.casefold() for marker in ("player", "embed", "vidmoly", "rapidrame", "m3u8", "mp4")):
                add(value)
        return values

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
        if not meta.search_queries:
            return []
        headers = {"User-Agent": self.USER_AGENT, "Referer": self.BASE_URL}
        streams: List[Stream] = []
        seen_streams: Set[str] = set()

        async with httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(8.0, connect=5.0), follow_redirects=True, verify=False) as client:
            target_url = ""
            for candidate in self._direct_title_urls(meta):
                try:
                    page = await client.get(candidate)
                    players = self._player_urls(page.text, candidate) if page.status_code == 200 else []
                    print(f"[{self.name}] direct {self._diagnostic(page)} players={len(players)}")
                    if players:
                        target_url = candidate
                        break
                except httpx.HTTPError as exc:
                    print(f"[{self.name}] direct error url={candidate}: {exc}")

            if not target_url:
                for query in meta.search_queries:
                    try:
                        response = await client.get(f"{self.BASE_URL}/?s={urllib.parse.quote(query)}")
                        print(f"[{self.name}] fallback search {self._diagnostic(response)} query={query!r}")
                        if response.status_code != 200:
                            continue
                        candidates = self._candidate_urls(response.text, meta)
                        print(f"[{self.name}] fallback candidates={len(candidates)}")
                        for candidate in candidates[:10]:
                            page = await client.get(candidate)
                            players = self._player_urls(page.text, candidate) if page.status_code == 200 else []
                            if players:
                                target_url = candidate
                                break
                        if target_url:
                            break
                    except httpx.HTTPError as exc:
                        print(f"[{self.name}] fallback search error query={query!r}: {exc}")

            if not target_url:
                print(f"[{self.name}] no playable target found")
                return streams
            try:
                page = await client.get(target_url)
                if page.status_code != 200:
                    return streams
                limit = max(0, config.max_streams_per_provider)
                for player_url in self._player_urls(page.text, target_url)[:limit or None]:
                    try:
                        extracted = await self._extract(player_url, target_url)
                    except Exception as exc:
                        print(f"[{self.name}] extraction error url={player_url}: {type(exc).__name__}: {exc}")
                        continue
                    if not extracted or not extracted.get("url"):
                        continue
                    stream_url = extracted["url"]
                    if stream_url in seen_streams:
                        continue
                    seen_streams.add(stream_url)
                    quality = extracted.get("quality") or "1080p"
                    streams.append(Stream(name=f"[TR DUBLAJ] ⚡ {self.name}", title=f"{meta.original_title}\n🔊 Türkçe Dublaj | 🎬 {quality} | HLS Stream", url=stream_url, behaviorHints=BehaviorHints(proxyHeaders=extracted.get("headers") or headers)))
            except httpx.HTTPError as exc:
                print(f"[{self.name}] target request error: {exc}")
        return streams
