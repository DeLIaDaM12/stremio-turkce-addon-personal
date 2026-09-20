import re
import urllib.parse
from typing import List, Set, Tuple

import httpx
from bs4 import BeautifulSoup

from app.models import Stream, UserConfig, BehaviorHints
from app.services.metadata import MediaMeta
from app.providers.base import BaseProvider
from app.extractors.vidmoly import VidmolyExtractor
from app.extractors.rapidrame import RapidrameExtractor
from app.extractors.generic_hls import GenericHlsExtractor


class HdFilmCehennemiProvider(BaseProvider):
    name = "HDFilmCehennemi"
    is_torrent = False
    BASE_URL = "https://www.hdfilmcehennemi.nl"  # Active mirror

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
    def _matches_result(title_text: str, meta: MediaMeta) -> bool:
        if not title_text:
            return True

        title = title_text.lower()
        title_candidates = [
            value.lower()
            for value in (meta.original_title, meta.turkish_title)
            if value
        ]

        if title_candidates and any(candidate in title for candidate in title_candidates):
            return True

        if meta.year:
            accepted_years = {meta.year - 1, meta.year, meta.year + 1}
            return any(str(year) in title for year in accepted_years)

        return not title_candidates

    @staticmethod
    def _episode_suffix(meta: MediaMeta) -> str:
        if meta.media_type != "series" or not meta.season or not meta.episode:
            return ""
        return f"-{meta.season}-sezon-{meta.episode}-bolum"

    def _find_target_candidates(
        self,
        soup: BeautifulSoup,
        meta: MediaMeta,
    ) -> List[str]:
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
        ]

        for result in soup.select(",".join(selectors)):
            link_tag = result if result.name == "a" else result.find("a")
            if not link_tag:
                continue

            href = link_tag.get("href")
            if not href:
                continue

            full_url = self._normalize_url(self.BASE_URL, href)
            if not full_url or full_url in seen:
                continue

            title_text = (
                link_tag.get("title")
                or link_tag.get_text(" ", strip=True)
                or result.get_text(" ", strip=True)
            )
            if meta.year and not self._matches_result(title_text, meta):
                continue

            seen.add(full_url)
            suffix = self._episode_suffix(meta)
            if suffix:
                episode_url = full_url.rstrip("/")
                if not episode_url.lower().endswith(suffix.lower()):
                    episode_url += suffix
                full_url = episode_url + "/"

            candidates.append(full_url)

        return candidates

    def _collect_player_links(
        self,
        soup: BeautifulSoup,
        page_url: str,
    ) -> List[Tuple[str, str]]:
        player_links: List[Tuple[str, str]] = []
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

            frame_url = self._normalize_url(page_url, frame_url)
            if not frame_url or frame_url in seen:
                continue

            label = node.get_text(" ", strip=True).lower()
            frame_lower = frame_url.lower()
            is_dubbed = any(
                marker in label or marker in frame_lower
                for marker in ("dublaj", "türkçe ses", "turkce ses", "dub", "tr")
            )
            audio_type = "Türkçe Dublaj" if is_dubbed else "Türkçe Altyazı"

            # Ignore unrelated embeds such as advertising frames.
            if not any(
                marker in frame_lower
                for marker in ("vidmoly", "rapidrame", "close", "player", ".m3u8")
            ):
                continue

            seen.add(frame_url)
            player_links.append((frame_url, audio_type))

        return player_links

    async def _extract_player(
        self,
        frame_url: str,
        target_url: str,
    ):
        frame_lower = frame_url.lower()
        if "vidmoly" in frame_lower:
            return await self.vidmoly.extract(frame_url, referer=target_url)
        if any(marker in frame_lower for marker in ("rapidrame", "close", "player")):
            return await self.rapidrame.extract(frame_url, referer=target_url)
        return await self.generic_hls.extract(frame_url, referer=target_url)

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        streams: List[Stream] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": self.BASE_URL,
        }

        async with httpx.AsyncClient(
            headers=headers,
            timeout=8.0,
            follow_redirects=True,
            verify=False,
        ) as client:
            target_url = None

            for query in meta.search_queries:
                try:
                    search_url = f"{self.BASE_URL}/search/{urllib.parse.quote(query)}"
                    response = await client.get(search_url)
                    if response.status_code != 200:
                        continue

                    soup = BeautifulSoup(response.text, "html.parser")
                    candidates = self._find_target_candidates(soup, meta)

                    # Try several candidates so an unrelated first result does not stop the search.
                    for candidate in candidates[:10]:
                        try:
                            candidate_response = await client.get(candidate)
                            if candidate_response.status_code != 200:
                                continue

                            candidate_soup = BeautifulSoup(candidate_response.text, "html.parser")
                            if self._collect_player_links(candidate_soup, candidate):
                                target_url = candidate
                                break
                        except Exception as exc:
                            print(f"[{self.name}] Candidate error for {candidate}: {exc}")

                    if target_url:
                        break
                except Exception as exc:
                    print(f"[{self.name}] Search error for '{query}': {exc}")

            if not target_url:
                return streams

            try:
                page_response = await client.get(target_url)
                if page_response.status_code != 200:
                    return streams

                page_soup = BeautifulSoup(page_response.text, "html.parser")
                player_links = self._collect_player_links(page_soup, target_url)
                seen_stream_urls: Set[str] = set()

                # Direct HLS URLs can be present in page markup without an iframe.
                direct_hls_urls = re.findall(
                    r"https?://[^\"'\s<>]+\.m3u8(?:\?[^\"'\s<>]*)?",
                    page_response.text,
                    flags=re.IGNORECASE,
                )
                for stream_url in direct_hls_urls:
                    if stream_url not in seen_stream_urls:
                        player_links.append((stream_url, "Türkçe Dublaj"))

                for frame_url, audio_type in player_links[: config.max_streams_per_provider]:
                    extracted = await self._extract_player(frame_url, target_url)
                    if not extracted or not extracted.get("url"):
                        continue

                    stream_url = extracted["url"]
                    if stream_url in seen_stream_urls:
                        continue
                    seen_stream_urls.add(stream_url)

                    quality = extracted.get("quality") or "1080p"
                    stream_name = (
                        f"[TR DUBLAJ] ⚡ {self.name}"
                        if audio_type == "Türkçe Dublaj"
                        else f"[TR ALTYAZI] ⚡ {self.name}"
                    )
                    stream_title = (
                        f"{meta.original_title}\n"
                        f"🔊 {audio_type} | 🎬 {quality} | HLS Stream"
                    )
                    proxy_headers = extracted.get("headers") or {
                        "Referer": target_url,
                        "User-Agent": headers["User-Agent"],
                    }

                    streams.append(
                        Stream(
                            name=stream_name,
                            title=stream_title,
                            url=stream_url,
                            behaviorHints=BehaviorHints(proxyHeaders=proxy_headers),
                        )
                    )
            except Exception as exc:
                print(f"[{self.name}] Error extracting streams: {exc}")

        return streams
