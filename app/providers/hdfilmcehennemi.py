import re
import urllib.parse
import httpx
from bs4 import BeautifulSoup
from typing import List, Optional
from app.models import Stream, UserConfig, BehaviorHints
from app.services.metadata import MediaMeta
from app.providers.base import BaseProvider
from app.extractors.vidmoly import VidmolyExtractor
from app.extractors.rapidrame import RapidrameExtractor
from app.extractors.generic_hls import GenericHlsExtractor

class HdFilmCehennemiProvider(BaseProvider):
    name = "HDFilmCehennemi"
    is_torrent = False
    BASE_URL = "https://www.hdfilmcehennemi.ws"  # Active mirror

    def __init__(self):
        self.vidmoly = VidmolyExtractor()
        self.rapidrame = RapidrameExtractor()
        self.generic_hls = GenericHlsExtractor()

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        streams: List[Stream] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": self.BASE_URL
        }

        async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True, verify=False) as client:
            target_url = None

            # Search queries in priority order
            for query in meta.search_queries:
                try:
                    search_url = f"{self.BASE_URL}/search/{urllib.parse.quote(query)}"
                    resp = await client.get(search_url)
                    if resp.status_code != 200:
                        continue
                    
                    soup = BeautifulSoup(resp.text, "html.parser")
                    results = soup.select(".poster.poster-pop, .card-body a, .poster-media")
                    
                    for r in results:
                        link_tag = r if r.name == "a" else r.find("a")
                        if not link_tag or not link_tag.get("href"):
                            continue
                        
                        href = link_tag.get("href")
                        title_text = link_tag.get("title") or r.get_text() or ""
                        
                        # Match year if available
                        if meta.year and str(meta.year) not in title_text and str(meta.year - 1) not in title_text and str(meta.year + 1) not in title_text:
                            # Still allow if name is a very close match
                            pass
                        
                        full_url = href if href.startswith("http") else f"{self.BASE_URL}{href}"
                        
                        if meta.media_type == "series":
                            # For series, check episode URL pattern
                            if meta.season and meta.episode:
                                ep_suffix = f"-{meta.season}-sezon-{meta.episode}-bolum"
                                # Check if page is series or direct episode
                                full_url = f"{full_url.rstrip('/')}{ep_suffix}/"
                        
                        target_url = full_url
                        break
                    
                    if target_url:
                        break
                except Exception as e:
                    print(f"[{self.name}] Search error for {query}: {e}")

            if not target_url:
                return streams

            # Fetch media page
            try:
                page_resp = await client.get(target_url)
                if page_resp.status_code != 200:
                    return streams

                page_html = page_resp.text
                page_soup = BeautifulSoup(page_html, "html.parser")

                # Extract video iframe sources or tabs (Dublaj / Altyazı)
                player_links = []
                
                # Check for language options / video players
                nav_tabs = page_soup.select("nav.nav-tab a, .nav-tabs a, button[data-bs-target], a[data-frame], a[href*='/player/']")
                for tab in nav_tabs:
                    frame_url = tab.get("data-frame") or tab.get("data-src") or tab.get("href")
                    label = tab.get_text().strip()
                    if frame_url and "http" in frame_url:
                        is_dubbed = "dublaj" in label.lower() or "türkçe ses" in label.lower() or "tr" in label.lower()
                        player_links.append((frame_url, "Türkçe Dublaj" if is_dubbed else "Türkçe Altyazı"))

                # Fallback to iframes inside the player container
                if not player_links:
                    iframes = page_soup.select("iframe[src*='player'], iframe[src*='vidmoly'], iframe[src*='rapidrame'], iframe[src*='close']")
                    for ifr in iframes:
                        src = ifr.get("src")
                        if src:
                            player_links.append((src if src.startswith("http") else f"https:{src}", "Türkçe Dublaj"))

                # Process extracted players
                for frame_url, audio_type in player_links[:config.max_streams_per_provider]:
                    # Extract stream with Vidmoly / Rapidrame / Generic
                    extracted = None
                    if "vidmoly" in frame_url:
                        extracted = await self.vidmoly.extract(frame_url, referer=target_url)
                    elif "rapidrame" in frame_url or "close" in frame_url or "player" in frame_url:
                        extracted = await self.rapidrame.extract(frame_url, referer=target_url)
                    else:
                        extracted = await self.generic_hls.extract(frame_url, referer=target_url)

                    if extracted and extracted.get("url"):
                        stream_url = extracted["url"]
                        quality = extracted.get("quality", "1080p")
                        
                        stream_name = f"[TR DUBLAJ] ⚡ {self.name}" if "Dublaj" in audio_type else f"[TR ALTYAZI] ⚡ {self.name}"
                        stream_title = f"{meta.original_title}\n🔊 {audio_type} | 🎬 {quality} | HLS Stream"
                        
                        streams.append(
                            Stream(
                                name=stream_name,
                                title=stream_title,
                                url=stream_url,
                                behaviorHints=BehaviorHints(
                                    proxyHeaders=extracted.get("headers")
                                )
                            )
                        )
            except Exception as e:
                print(f"[{self.name}] Error extracting streams: {e}")

        return streams
