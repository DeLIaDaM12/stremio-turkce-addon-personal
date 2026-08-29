import re
import urllib.parse
import httpx
from bs4 import BeautifulSoup
from typing import List
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

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        if meta.media_type != "movie":
            return []  # Primarily movies

        streams: List[Stream] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": self.BASE_URL
        }

        async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True, verify=False) as client:
            target_url = None

            for query in meta.search_queries:
                try:
                    search_url = f"{self.BASE_URL}/arama/{urllib.parse.quote(query)}"
                    resp = await client.get(search_url)
                    if resp.status_code != 200:
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")
                    items = soup.select(".film-list a, .film-item a, a.film-link")
                    for a in items:
                        href = a.get("href")
                        if not href:
                            continue
                        target_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                        break
                    
                    if target_url:
                        break
                except Exception as e:
                    print(f"[{self.name}] Search error: {e}")

            if not target_url:
                return streams

            try:
                page_resp = await client.get(target_url)
                if page_resp.status_code == 200:
                    page_html = page_resp.text
                    soup = BeautifulSoup(page_html, "html.parser")
                    
                    # Extract player sources / iframes
                    sources = soup.select("iframe, .player-area iframe, a[data-frame]")
                    for s in sources:
                        frame_url = s.get("src") or s.get("data-frame")
                        if frame_url:
                            extracted = None
                            if "vidmoly" in frame_url:
                                extracted = await self.vidmoly.extract(frame_url, referer=target_url)
                            else:
                                extracted = await self.generic_hls.extract(frame_url, referer=target_url)

                            if extracted and extracted.get("url"):
                                streams.append(
                                    Stream(
                                        name=f"[TR DUBLAJ] ⚡ {self.name}",
                                        title=f"{meta.original_title}\n🔊 Türkçe Dublaj | 🎬 1080p Full HD",
                                        url=extracted["url"],
                                        behaviorHints=BehaviorHints(
                                            proxyHeaders=extracted.get("headers")
                                        )
                                    )
                                )
            except Exception as e:
                print(f"[{self.name}] Stream error: {e}")

        return streams
