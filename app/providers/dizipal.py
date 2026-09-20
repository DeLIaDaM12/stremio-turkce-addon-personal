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
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self):
        self.generic_hls = GenericHlsExtractor()
        self.vidmoly = VidmolyExtractor()

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

    def _candidate_urls(self, html: str, meta: MediaMeta) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        seen: Set[str] = set()
        candidates: List[str] = []
        selectors = [
            "article a",
            ".search-result a",
            ".movies-list a",
            ".film a",
            ".movie a",
            "a[href*='/film/']",
            "a[href*='/dizi/']",
            "a[href*='/series/']",
        ]
        for node in soup.select(",".join(selectors)):
            href = node.get("href")
            if not href:
                continue
            url = self._normalize_url(self.BASE_URL, href)
            if not url or url in seen:
                continue
            seen.add(url)
            title_text = node.get("title") or node.get_text(" ", strip=True) or ""
            if meta.year and not self._title_matches(title_text, meta):
                continue
            candidates.append(url)
        return candidates

    def _extract_stream_urls(self, html: str, soup: BeautifulSoup, page_url: str) -> List[str]:
        urls: List[str] = []
        seen: Set[str] = set()
        for match in re.findall(r'"?(https?://[^"\'\s>]+\.m3u8(?:\?[^"\'\s>]*)?)"?', html, flags=re.IGNORECASE):
            url = match
            if url not in seen:
                seen.add(url)
                urls.append(url)
        for node in soup.select("iframe, source, script, a[href*='.m3u8'], a[data-src], a[data-frame]"):
            raw = node.get("src") or node.get("data-src") or node.get("data-frame") or node.get("href")
            if not raw:
                continue
            if ".m3u8" not in raw.lower():
                continue
            url = self._normalize_url(page_url, raw)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        return urls

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        streams: List[Stream] = []
        headers = {"User-Agent": self.USER_AGENT, "Referer": self.BASE_URL}

        async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True, verify=False) as client:
            target_url = ""
            for query in meta.search_queries:
                try:
                    search_url = f"{self.BASE_URL}/find?q={urllib.parse.quote(query)}"
                    response = await client.get(search_url)
                    if response.status_code != 200:
                        continue
                    candidates = self._candidate_urls(response.text, meta)
                    for candidate in candidates[:10]:
                        try:
                            page = await client.get(candidate)
                            if page.status_code != 200:
                                continue
                            page_soup = BeautifulSoup(page.text, "html.parser")
                            if self._extract_stream_urls(page.text, page_soup, candidate):
                                target_url = candidate
                                break
                        except Exception as exc:
                            print(f"[{self.name}] Candidate error {candidate}: {exc}")
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
                for stream_url in self._extract_stream_urls(page_response.text, page_soup, target_url)[: config.max_streams_per_provider]:
                    extracted = None
                    if "vidmoly" in stream_url.casefold():
                        extracted = await self.vidmoly.extract(stream_url, referer=target_url)
                    else:
                        extracted = await self.generic_hls.extract(stream_url, referer=target_url)
                    if not extracted or not extracted.get("url"):
                        continue
                    streams.append(
                        Stream(
                            name=f"[TR DUBLAJ] ⚡ {self.name}",
                            title=f"{meta.original_title}\n🔊 Türkçe Dublaj | 🎬 {extracted.get('quality', '1080p')} | HLS Stream",
                            url=extracted["url"],
                            behaviorHints=BehaviorHints(
                                proxyHeaders=extracted.get("headers") or {
                                    "Referer": target_url,
                                    "User-Agent": self.USER_AGENT,
                                }
                            ),
                        )
                    )
            except Exception as exc:
                print(f"[{self.name}] Stream extraction error: {exc}")

        return streams
