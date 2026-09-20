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
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
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
        names = [value.casefold() for value in (meta.original_title, meta.turkish_title) if value]
        if not names:
            return True
        if any(name in title for name in names):
            return True
        return bool(meta.year and any(str(meta.year + offset) in title for offset in (-1, 0, 1)))

    def _episode_url(self, series_url: str, meta: MediaMeta) -> str:
        base = series_url.rstrip("/")
        suffix = f"-{meta.season}-sezon-{meta.episode}-bolum-izle"
        if base.casefold().endswith(suffix.casefold()):
            return base + "/"
        return f"{base}{suffix}/"

    def _candidate_urls(self, html: str, meta: MediaMeta) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        candidates: List[str] = []
        seen: Set[str] = set()
        for node in soup.select(
            ".post-content a, .entry-title a, article a, .title a, .post a, "
            ".item a, .poster a, .card a, a[rel='bookmark'], "
            "a[href*='/dizi/'], a[href*='/series/']"
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

        for value in re.findall(r"(?:https?:)?//[^\"'<>\s\\]+", html, re.IGNORECASE):
            lower = value.casefold()
            if any(marker in lower for marker in ("player", "embed", "m3u8", "mp4", "vidmoly", "rapidrame")):
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

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        if meta.media_type != "series" or not meta.season or not meta.episode:
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
                    response = await client.get(self.BASE_URL, params={"s": query})
                    print(f"[{self.name}] search {self._diagnostic(response)} query={query!r}")
                    if response.status_code != 200:
                        continue
                    candidates = self._candidate_urls(response.text, meta)
                    print(f"[{self.name}] candidates={len(candidates)}")
                    for candidate in candidates[:10]:
                        try:
                            page = await client.get(candidate)
                            players = self._player_urls(page.text, candidate) if page.status_code == 200 else []
                            print(f"[{self.name}] candidate {self._diagnostic(page)} players={len(players)}")
                            if players:
                                target_url = candidate
                                break
                        except httpx.HTTPError as exc:
                            print(f"[{self.name}] candidate error url={candidate}: {exc}")
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
                        extracted = await self.generic_hls.extract(player_url, referer=target_url)
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
                    streams.append(Stream(
                        name=f"[TR DUBLAJ/ALT] ⚡ {self.name}",
                        title=(
                            f"{meta.original_title} S{meta.season:02d}E{meta.episode:02d}\n"
                            f"🔊 Türkçe Ses / Altyazı | 🎬 {quality}"
                        ),
                        url=stream_url,
                        behaviorHints=BehaviorHints(proxyHeaders=extracted.get("headers") or headers),
                    ))
            except httpx.HTTPError as exc:
                print(f"[{self.name}] target request error: {exc}")

        print(f"[{self.name}] returning {len(streams)} stream(s)")
        return streams
