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

    def __init__(self):
        self.vidmoly = VidmolyExtractor()
        self.rapidrame = RapidrameExtractor()
        self.generic_hls = GenericHlsExtractor()

    @staticmethod
    def _normalize_url(base_url: str, href: str) -> str:
        if not href:
            return ""
        href = href.strip()
        if href.startswith(("http://", "https://")):
            return href
        if href.startswith("//"):
            return "https:" + href
        return urllib.parse.urljoin(base_url.rstrip("/") + "/", href)

    @staticmethod
    def _title_matches(title_text: str, meta: MediaMeta) -> bool:
        if not title_text:
            return True
        title = title_text.casefold()
        for value in (meta.original_title, meta.turkish_title):
            if value and value.casefold() in title:
                return True
        if meta.year:
            for offset in (-1, 0, 1):
                if str(meta.year + offset) in title:
                    return True
        return False

    def _search_candidates(self, html: str, meta: MediaMeta, base_url: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        candidates: List[str] = []
        seen: Set[str] = set()
        selectors = [
            ".poster.poster-pop",
            ".card-body a",
            ".poster-media",
            "article a",
            ".film-list a",
            ".film-item a",
            "a.film-link",
            "a[href*='/film/']",
            "a[href*='/dizi/']",
            "a[href*='/series/']",
        ]

        for node in soup.select(",".join(selectors)):
            link = node if node.name == "a" else node.find("a")
            if not link:
                continue
            href = link.get("href")
            if not href:
                continue
            url = self._normalize_url(base_url, href)
            if not url or url in seen:
                continue
            title = link.get("title") or node.get_text(" ", strip=True) or ""
            if meta.year and not self._title_matches(title, meta):
                continue
            seen.add(url)
            if meta.media_type == "series" and meta.season and meta.episode:
                suffix = f"-{meta.season}-sezon-{meta.episode}-bolum"
                if not url.casefold().endswith(suffix.casefold()):
                    url = f"{url.rstrip('/')} {suffix}/".replace(" ", "")
            candidates.append(url)
        return candidates

    @staticmethod
    def _player_type(frame_url: str, label: str) -> str:
        label_lower = (label or "").casefold()
        frame_lower = frame_url.casefold()
        if any(word in label_lower for word in ("dublaj", "turkce ses", "turkçe ses", "tr")):
            return "Türkçe Dublaj"
        if any(word in label_lower for word in ("altyazi", "alt yaz", "subtitles")):
            return "Türkçe Altyazı"
        if any(word in frame_lower for word in ("dublaj", "dub", "turkce")):
            return "Türkçe Dublaj"
        return "Türkçe Altyazı"

    def _collect_players(self, html: str, page_url: str) -> List[Tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        players: List[Tuple[str, str]] = []
        seen: Set[str] = set()
        selectors = [
            "nav.nav-tab a",
            ".nav-tabs a",
            "button[data-bs-target]",
            "a[data-frame]",
            "a[data-src]",
            "a[href*='/player/']",
            "iframe",
        ]

        for node in soup.select(",".join(selectors)):
            frame_url = (
                node.get("data-frame")
                or node.get("data-src")
                or node.get("src")
                or node.get("href")
            )
            if not frame_url:
                continue
            url = self._normalize_url(page_url, frame_url)
            if not url or url in seen:
                continue
            if not any(marker in url.casefold() for marker in ("player", "vidmoly", "rapidrame", "close", ".m3u8")):
                continue
            label = node.get_text(" ", strip=True) or ""
            seen.add(url)
            players.append((url, self._player_type(url, label)))

        if players:
            return players

        for match in re.findall(r'"?(https?://[^"\'\s>]+\.m3u8(?:\?[^"\'\s>]*)?)"?', html, flags=re.IGNORECASE):
            if match not in seen:
                seen.add(match)
                players.append((match, "Türkçe Dublaj"))

        return players

    async def _extract_player(self, frame_url: str, referer: str):
        lower = frame_url.casefold()
        if "vidmoly" in lower:
            return await self.vidmoly.extract(frame_url, referer=referer)
        if any(marker in lower for marker in ("rapidrame", "close", "player")):
            return await self.rapidrame.extract(frame_url, referer=referer)
        return await self.generic_hls.extract(frame_url, referer=referer)

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        streams: List[Stream] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": self.ACTIVE_MIRRORS[0],
        }

        async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True, verify=False) as client:
            target_url = ""
            for base_url in self.ACTIVE_MIRRORS:
                for query in meta.search_queries:
                    try:
                        response = await client.get(f"{base_url}/search/{urllib.parse.quote(query)}")
                        if response.status_code != 200:
                            continue
                        for candidate in self._search_candidates(response.text, meta, base_url)[:10]:
                            try:
                                page = await client.get(candidate)
                                if page.status_code != 200:
                                    continue
                                if self._collect_players(page.text, candidate):
                                    target_url = candidate
                                    break
                            except Exception as exc:
                                print(f"[{self.name}] Candidate error for {candidate}: {exc}")
                        if target_url:
                            break
                    except Exception as exc:
                        print(f"[{self.name}] Search error for '{query}' on {base_url}: {exc}")
                if target_url:
                    break

            if not target_url:
                return streams

            try:
                page_response = await client.get(target_url)
                if page_response.status_code != 200:
                    return streams

                player_links = self._collect_players(page_response.text, target_url)
                seen: Set[str] = set()
                for frame_url, audio_type in player_links[: config.max_streams_per_provider]:
                    if frame_url in seen:
                        continue
                    seen.add(frame_url)
                    extracted = await self._extract_player(frame_url, target_url)
                    if not extracted or not extracted.get("url"):
                        continue
                    stream_url = extracted["url"]
                    quality = extracted.get("quality") or "1080p"
                    stream_name = f"[TR DUBLAJ] ⚡ {self.name}" if "Dublaj" in audio_type else f"[TR ALTYAZI] ⚡ {self.name}"
                    stream_title = f"{meta.original_title}\n🔊 {audio_type} | 🎬 {quality} | HLS Stream"
                    streams.append(
                        Stream(
                            name=stream_name,
                            title=stream_title,
                            url=stream_url,
                            behaviorHints=BehaviorHints(
                                proxyHeaders=extracted.get("headers") or {
                                    "Referer": target_url,
                                    "User-Agent": headers["User-Agent"],
                                }
                            ),
                        )
                    )
            except Exception as exc:
                print(f"[{self.name}] Error extracting streams: {exc}")

        return streams
