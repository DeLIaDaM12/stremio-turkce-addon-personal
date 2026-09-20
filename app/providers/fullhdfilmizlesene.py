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

    def __init__(self):
        self.generic_hls = GenericHlsExtractor()
        self.vidmoly = VidmolyExtractor()

    @staticmethod
    def _url(base: str, value: str) -> str:
        return urllib.parse.urljoin(base.rstrip("/") + "/", value.strip()) if value else ""

    @staticmethod
    def _media_urls(html: str, base: str) -> List[str]:
        values = re.findall(r"(?:https?:)?//[^\"'<>\\s]+\.(?:m3u8|mp4)(?:\?[^\"'<>\\s]*)?", html, re.I)
        values += re.findall(r"(?:src|file|source|url)\s*[:=]\s*[\"']([^\"']+)", html, re.I)
        result, seen = [], set()
        for value in values:
            value = value.replace("\\/", "/")
            value = "https:" + value if value.startswith("//") else FullHdFilmizleseneProvider._url(base, value)
            if (".m3u8" in value.lower() or ".mp4" in value.lower()) and value not in seen:
                seen.add(value)
                result.append(value)
        return result

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        if meta.media_type != "movie":
            return []
        headers = {"User-Agent": "Mozilla/5.0", "Referer": self.BASE_URL}
        async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True, verify=False) as client:
            target = ""
            for query in meta.search_queries:
                try:
                    response = await client.get(f"{self.BASE_URL}/arama/{urllib.parse.quote(query)}")
                    if response.status_code != 200:
                        continue
                    soup = BeautifulSoup(response.text, "html.parser")
                    for link in soup.select(".film-list a, .film-item a, a.film-link, article a"):
                        href = link.get("href")
                        if not href:
                            continue
                        candidate = self._url(self.BASE_URL, href)
                        page = await client.get(candidate)
                        if page.status_code == 200 and (self._media_urls(page.text, candidate) or page.text.count("<iframe") > 0):
                            target = candidate
                            break
                    if target:
                        break
                except (httpx.HTTPError, ValueError) as exc:
                    print(f"[{self.name}] Search error: {exc}")
            if not target:
                return []
            page = await client.get(target)
            soup = BeautifulSoup(page.text, "html.parser")
            sources = self._media_urls(page.text, target)
            sources += [self._url(target, n.get("src") or n.get("data-src") or n.get("data-frame")) for n in soup.select("iframe, source, a[data-frame], a[data-src]")]
            streams, seen = [], set()
            for source in [s for s in sources if s][: max(0, config.max_streams_per_provider) or None]:
                extracted = await (self.vidmoly if "vidmoly" in source.lower() else self.generic_hls).extract(source, referer=target)
                if not extracted or not extracted.get("url") or extracted["url"] in seen:
                    continue
                seen.add(extracted["url"])
                streams.append(Stream(name=f"[TR DUBLAJ] ⚡ {self.name}", title=f"{meta.original_title} | 🎬 {extracted.get('quality', '1080p')}", url=extracted["url"], behaviorHints=BehaviorHints(proxyHeaders=extracted.get("headers") or headers)))
            return streams
