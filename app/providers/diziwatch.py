import re
import urllib.parse
import httpx
from bs4 import BeautifulSoup
from typing import List
from app.models import Stream, UserConfig, BehaviorHints
from app.services.metadata import MediaMeta
from app.providers.base import BaseProvider
from app.extractors.generic_hls import GenericHlsExtractor

class DiziWatchProvider(BaseProvider):
    name = "DiziWatch"
    is_torrent = False
    BASE_URL = "https://diziwatch.ac"

    def __init__(self):
        self.generic_hls = GenericHlsExtractor()

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        if meta.media_type != "series" or not meta.season or not meta.episode:
            return []

        streams: List[Stream] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": self.BASE_URL
        }

        async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True) as client:
            target_url = None

            for query in meta.search_queries:
                try:
                    search_url = f"{self.BASE_URL}/?s={urllib.parse.quote(query)}"
                    resp = await client.get(search_url)
                    if resp.status_code != 200:
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")
                    items = soup.select(".post-content a, .entry-title a, article a")
                    for a in items:
                        href = a.get("href")
                        if not href:
                            continue
                        # Build episode link: diziwatch.net/dizi-adi-season-sezon-episode-bolum-izle/
                        base_slug = href.rstrip("/")
                        target_url = f"{base_slug}-{meta.season}-sezon-{meta.episode}-bolum-izle/"
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
                    # Extract player link or m3u8
                    m = re.search(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', page_html)
                    if m:
                        streams.append(
                            Stream(
                                name=f"[TR DUBLAJ/ALT] ⚡ {self.name}",
                                title=f"{meta.original_title} S{meta.season:02d}E{meta.episode:02d}\n🔊 Türkçe Ses / Altyazı | 🎬 1080p",
                                url=m.group(1),
                                behaviorHints=BehaviorHints(
                                    proxyHeaders={"Referer": target_url, "User-Agent": headers["User-Agent"]}
                                )
                            )
                        )
            except Exception as e:
                print(f"[{self.name}] Stream error: {e}")

        return streams
