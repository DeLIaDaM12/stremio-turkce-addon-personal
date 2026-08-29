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

class DizipalProvider(BaseProvider):
    name = "Dizipal"
    is_torrent = False
    BASE_URL = "https://dizipal.buzz"  # Active mirror

    def __init__(self):
        self.generic_hls = GenericHlsExtractor()
        self.vidmoly = VidmolyExtractor()

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        streams: List[Stream] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": self.BASE_URL
        }

        async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True, verify=False) as client:
            target_url = None

            for query in meta.search_queries:
                try:
                    search_url = f"{self.BASE_URL}/find?q={urllib.parse.quote(query)}"
                    resp = await client.get(search_url)
                    if resp.status_code != 200:
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")
                    articles = soup.select("article a, .search-result a, .movies-list a")
                    for a in articles:
                        href = a.get("href")
                        if not href:
                            continue
                        full_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                        
                        if meta.media_type == "series" and meta.season and meta.episode:
                            target_url = f"{full_url.rstrip('/')}-sezon-{meta.season}-bolum-{meta.episode}"
                        else:
                            target_url = full_url
                        break
                    
                    if target_url:
                        break
                except Exception as e:
                    print(f"[{self.name}] Search error for {query}: {e}")

            if not target_url:
                return streams

            try:
                page_resp = await client.get(target_url)
                if page_resp.status_code == 200:
                    page_html = page_resp.text
                    
                    # Search for m3u8 or video embed links
                    m = re.search(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', page_html)
                    if m:
                        stream_url = m.group(1)
                        streams.append(
                            Stream(
                                name=f"[TR DUBLAJ] ⚡ {self.name}",
                                title=f"{meta.original_title}\n🔊 Türkçe Dublaj | 🎬 1080p Full HD",
                                url=stream_url,
                                behaviorHints=BehaviorHints(
                                    proxyHeaders={"Referer": target_url, "User-Agent": headers["User-Agent"]}
                                )
                            )
                        )
            except Exception as e:
                print(f"[{self.name}] Stream extraction error: {e}")

        return streams
