import re
import urllib.parse
from typing import List, Set, Tuple

import httpx
from bs4 import BeautifulSoup

from app.extractors.generic_hls import GenericHlsExtractor
from app.extractors.rapidrame import RapidrameExtractor
from app.extractors.vidmoly import VidmolyExtractor
from app.models import BehaviorHints, Stream, UserConfig
from app.providers.base import BaseProvider
from app.services.metadata import MediaMeta


class HdFilmCehennemiProvider(BaseProvider):
    name = "HDFilmCehennemi"
    is_torrent = False
    ACTIVE_MIRRORS = (
        "https://www.hdfilmcehennemi.ws",
        "https://www.hdfilmcehennemi.nl",
    )
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self) -> None:
        self.vidmoly = VidmolyExtractor()
        self.rapidrame = RapidrameExtractor()
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
    def _title_matches(title_text: str, meta: MediaMeta) -> bool:
        if not title_text:
            return True
        title = title_text.casefold()
        title_values = [value.casefold() for value in (meta.original_title, meta.turkish_title) if value]
        if not title_values:
            return True
        if any(value in title for value in title_values):
            return True
        if meta.year:
            return any(str(meta.year + offset) in title for offset in (-1, 0, 1))
        return False

    def _search_candidates(self, html: str, meta: MediaMeta, base_url: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        selectors = (
            ".poster.poster-pop, .card-body a, .poster-media, article a, "
            ".film-list a, .film-item a, a.film-link, a[href*='/film/'], "
            "a[href*='/dizi/'], a[href*='/series/']"
        )
        candidates: List[str] = []
        seen: Set[str] = set()

        for node in soup.select(selectors):
            link = node if node.name == "a" else node.find("a")
            if not link:
                continue
            url = self._normalize_url(base_url, link.get("href", ""))
            if not url or url in seen:
                continue

            label = link.get("title") or link.get_text(" ", strip=True) or node.get_text(" ", strip=True)
            if meta.year and not self._title_matches(label, meta):
                continue

            seen.add(url)
            if meta.media_type == "series" and meta.season and meta.episode:
                suffix = f"-{meta.season}-sezon-{meta.episode}-bolum"
                if not url.rstrip("/").casefold().endswith(suffix.casefold()):
                    url = f"{url.rstrip('/')}{suffix}/"
            candidates.append(url)

        return candidates

    @staticmethod
    def _audio_type(label: str, url: str) -> str:
        text = f"{label} {url}".casefold()
        if any(value in text for value in ("dublaj", "dub", "türkçe ses", "turkce ses")):
            return "Türkçe Dublaj"
        if any(value in text for value in ("altyazi", "alt yaz", "subtitle")):
            return "Türkçe Altyazı"
        return "Türkçe Dublaj"

    def _collect_players(self, html: str, page_url: str) -> List[Tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        selectors = (
            "nav.nav-tab a, .nav-tabs a, button[data-bs-target], a[data-frame], "
            "a[data-src], a[data-url], a[href*='/player/'], iframe, video source, source"
        )
        players: List[Tuple[str, str]] = []
        seen: Set[str] = set()

        for node in soup.select(selectors):
            raw_url = (
                node.get("data-frame")
                or node.get("data-src")
                or node.get("data-url")
                or node.get("src")
                or node.get("href")
            )
            url = self._normalize_url(page_url, raw_url or "")
            if not url or url in seen:
                continue
            seen.add(url)
            players.append((url, self._audio_type(node.get_text(" ", strip=True), url)))

        # Player URLs are also commonly embedded in JavaScript strings.
        for raw_url in re.findall(r"(?:https?:)?//[^\"'<>\s\\]+", html):
            url = self._normalize_url(page_url, raw_url)
            if not url or url in seen:
                continue
            lower = url.casefold()
            if any(marker in lower for marker in ("vidmoly", "rapidrame", "player", "close", ".m3u8", ".mp4")):
                seen.add(url)
                players.append((url, self._audio_type("", url)))

        return players

    async def _extract_player(self, url: str, referer: str):
        lower = url.casefold()
        if ".m3u8" in lower or ".mp4" in lower:
            return await self.generic_hls.extract(url, referer=referer)
        if "vidmoly" in lower:
            return await self.vidmoly.extract(url, referer=referer)
        if any(value in lower for value in ("rapidrame", "close", "player")):
            return await self.rapidrame.extract(url, referer=referer)
        return await self.generic_hls.extract(url, referer=referer)

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        headers = {"User-Agent": self.USER_AGENT, "Referer": self.ACTIVE_MIRRORS[0]}
        streams: List[Stream] = []
        seen_streams: Set[str] = set()

        async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True, verify=False) as client:
            target_url = ""
            for base_url in self.ACTIVE_MIRRORS:
                for query in meta.search_queries:
                    try:
                        response = await client.get(f"{base_url}/search/{urllib.parse.quote(query)}")
                        if response.status_code != 200:
                            continue
                        for candidate in self._search_candidates(response.text, meta, base_url)[:10]:
                            page = await client.get(candidate)
                            if page.status_code == 200 and self._collect_players(page.text, candidate):
                                target_url = candidate
                                break
                        if target_url:
                            break
                    except httpx.HTTPError as exc:
                        print(f"[{self.name}] Search error for '{query}': {exc}")
                if target_url:
                    break

            if not target_url:
                return streams

            try:
                response = await client.get(target_url)
                if response.status_code != 200:
                    return streams

                limit = max(0, config.max_streams_per_provider)
                players = self._collect_players(response.text, target_url)
                for player_url, audio_type in players[:limit or None]:
                    try:
                        extracted = await self._extract_player(player_url, target_url)
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
                            name=f"[TR DUBLAJ] ⚡ {self.name}" if audio_type == "Türkçe Dublaj" else f"[TR ALTYAZI] ⚡ {self.name}",
                            title=f"{meta.original_title}\n🔊 {audio_type} | 🎬 {quality} | HLS Stream",
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
