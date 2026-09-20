import re
import urllib.parse
from typing import List, Set

import httpx
from bs4 import BeautifulSoup

from app.models import Stream, UserConfig, BehaviorHints
from app.services.metadata import MediaMeta
from app.providers.base import BaseProvider
from app.extractors.generic_hls import GenericHlsExtractor
from app.extractors.vidmoly import VidmolyExtractor


class FullHdFilmizleseneProvider(BaseProvider):
    name = "FullHDFilmizlesene"
    is_torrent = False
    BASE_URL = "https://www.fullhdfilmizlesene.pw"  # Active mirror

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

        title = title_text.lower()
        for value in (meta.original_title, meta.turkish_title):
            if value and value.lower() in title:
                return True

        if meta.year:
            accepted_years = {meta.year - 1, meta.year, meta.year + 1}
            if any(str(year) in title for year in accepted_years):
                return True

        return False

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        if meta.media_type != "movie":
            return []

        streams: List[Stream] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": self.BASE_URL,
        }

        async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True, verify=False) as client:
            target_url = None

            for query in meta.search_queries:
                try:
                    search_url = f"{self.BASE_URL}/arama/{urllib.parse.quote(query)}"
                    response = await client.get(search_url)
                    if response.status_code != 200:
                        continue

                    soup = BeautifulSoup(response.text, "html.parser")
                    seen: Set[str] = set()

                    for item in soup.select(".film-list a, .film-item a, a.film-link, .movie a, article a"):
                        href = item.get("href")
                        if not href:
                            continue

                        full_url = self._normalize_url(self.BASE_URL, href)
                        if not full_url or full_url in seen:
                            continue
                        seen.add(full_url)

                        title_text = item.get("title") or item.get_text(" ", strip=True) or ""
                        if meta.year and not self._title_matches(title_text, meta):
                            continue

                        target_url = full_url
                        break

                    if target_url:
                        break
                except Exception as exc:
                    print(f"[{self.name}] Search error: {exc}")

            if not target_url:
                return streams

            try:
                page_response = await client.get(target_url)
                if page_response.status_code != 200:
                    return streams

                page_html = page_response.text
                page_soup = BeautifulSoup(page_html, "html.parser")

                stream_urls: Set[str] = set()

                for match in re.findall(r'"?(https?://[^"\'\s>]+\.m3u8(?:\?[^"\'\s>]*)?)"?', page_html, flags=re.IGNORECASE):
                    stream_urls.add(match)

                for tag in page_soup.select("iframe, source, script, a[href*='.m3u8'], a[data-frame], a[data-src]"):
                    raw = tag.get("src") or tag.get("data-src") or tag.get("data-frame") or tag.get("href")
                    if not raw:
                        continue
                    if ".m3u8" in raw.lower():
                        stream_urls.add(self._normalize_url(target_url, raw))

                for stream_url in sorted(stream_urls):
                    extracted = None
                    if "vidmoly" in stream_url.lower():
                        extracted = await self.vidmoly.extract(stream_url, referer=target_url)
                    else:
                        extracted = await self.generic_hls.extract(stream_url, referer=target_url)

                    if not extracted or not extracted.get("url"):
                        continue

                    quality = extracted.get("quality") or "1080p"
                    streams.append(
                        Stream(
                            name=f"[TR DUBLAJ] ⚡ {self.name}",
                            title=f"{meta.original_title}\n🔊 Türkçe Dublaj | 🎬 {quality} | HLS Stream",
                            url=extracted["url"],
                            behaviorHints=BehaviorHints(
                                proxyHeaders=extracted.get("headers") or {
                                    "Referer": target_url,
                                    "User-Agent": headers["User-Agent"],
                                }
                            ),
                        )
                    )
            except Exception as exc:
                print(f"[{self.name}] Stream error: {exc}")

        return streams
