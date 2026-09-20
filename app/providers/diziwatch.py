import re
import urllib.parse
from typing import List, Set

import httpx
from bs4 import BeautifulSoup

from app.models import BehaviorHints, Stream, UserConfig
from app.providers.base import BaseProvider
from app.services.metadata import MediaMeta
from app.extractors.generic_hls import GenericHlsExtractor


class DiziWatchProvider(BaseProvider):
    name = "DiziWatch"
    is_torrent = False
    BASE_URL = "https://diziwatch.net"

    def __init__(self):
        self.generic_hls = GenericHlsExtractor()

    @staticmethod
    def _url(base: str, value: str) -> str:
        return urllib.parse.urljoin(base.rstrip("/") + "/", value.strip()) if value else ""

    @staticmethod
    def _hls(html: str, base: str) -> List[str]:
        values = re.findall(r"(?:https?:)?//[^\"'<>\\s]+\.m3u8(?:\?[^\"'<>\\s]*)?", html, re.I)
        values += re.findall(r"(?:src|file|source|url)\s*[:=]\s*[\"']([^\"']+)", html, re.I)
        result, seen = [], set()
        for value in values:
            value = value.replace("\\/", "/")
            if value.startswith("//"):
                value = "https:" + value
            value = DiziWatchProvider._url(base, value)
            if ".m3u8" in value.lower() and value not in seen:
                seen.add(value)
                result.append(value)
        return result

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        if meta.media_type != "series" or not meta.season or not meta.episode:
            return []
        headers = {"User-Agent": "Mozilla/5.0", "Referer": self.BASE_URL}
        async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True, verify=False) as client:
            target = ""
            for query in meta.search_queries:
                try:
                    response = await client.get(f"{self.BASE_URL}/", params={"s": query})
                    if response.status_code != 200:
                        continue
                    soup = BeautifulSoup(response.text, "html.parser")
                    for link in soup.select(".post-content a, .entry-title a, article a, .title a"):
                        href = link.get("href")
                        if not href:
                            continue
                        base = self._url(self.BASE_URL, href).rstrip("/")
                        candidate = f"{base}-{meta.season}-sezon-{meta.episode}-bolum-izle/"
                        page = await client.get(candidate)
                        if page.status_code == 200 and self._hls(page.text, candidate):
                            target = candidate
                            break
                    if target:
                        break
                except (httpx.HTTPError, ValueError) as exc:
                    print(f"[{self.name}] Search error: {exc}")
            if not target:
                return []
            page = await client.get(target)
            urls = self._hls(page.text, target)[: max(0, config.max_streams_per_provider) or None]
            streams = []
            seen: Set[str] = set()
            for url in urls:
                extracted = await self.generic_hls.extract(url, referer=target)
                if not extracted or not extracted.get("url") or extracted["url"] in seen:
                    continue
                seen.add(extracted["url"])
                streams.append(Stream(
                    name=f"[TR DUBLAJ/ALT] ⚡ {self.name}",
                    title=f"{meta.original_title} S{meta.season:02d}E{meta.episode:02d} | 🎬 {extracted.get('quality', '1080p')}",
                    url=extracted["url"],
                    behaviorHints=BehaviorHints(proxyHeaders=extracted.get("headers") or headers),
                ))
            return streams
