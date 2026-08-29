import re
import urllib.parse
import httpx
from typing import List
from app.models import Stream, UserConfig
from app.services.metadata import MediaMeta
from app.providers.base import BaseProvider

class TurkTorrentProvider(BaseProvider):
    name = "TurkTorrent"
    is_torrent = True

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        if not config.enable_torrents:
            return []

        streams: List[Stream] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }

        search_terms = []
        if meta.original_title:
            if meta.media_type == "movie":
                search_terms.append(f"{meta.original_title} dual")
                search_terms.append(f"{meta.original_title} turkish")
                search_terms.append(f"{meta.original_title} tr")
            else:
                if meta.season and meta.episode:
                    search_terms.append(f"{meta.original_title} S{meta.season:02d}E{meta.episode:02d} dual")
                    search_terms.append(f"{meta.original_title} S{meta.season:02d} dual")
                else:
                    search_terms.append(f"{meta.original_title} dual")

        if meta.turkish_title and meta.turkish_title != meta.original_title:
            search_terms.append(f"{meta.turkish_title} dublaj")

        async with httpx.AsyncClient(headers=headers, timeout=6.0, follow_redirects=True) as client:
            # 1. Query Apibay (ThePirateBay API)
            for term in search_terms[:3]:
                try:
                    url = f"https://apibay.org/q.php?q={urllib.parse.quote(term)}"
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        if isinstance(data, list) and len(data) > 0 and data[0].get("name") != "No results returned":
                            for item in data[:4]:
                                name = item.get("name", "")
                                info_hash = item.get("info_hash", "").lower()
                                seeds = item.get("seeders", "0")
                                size_bytes = int(item.get("size", 0))
                                size_gb = f"{size_bytes / (1024**3):.1f} GB" if size_bytes > 0 else ""

                                if not info_hash or info_hash == "0000000000000000000000000000000000000000":
                                    continue

                                res = "1080p"
                                if "2160p" in name or "4k" in name.lower():
                                    res = "4K 2160p"
                                elif "720p" in name:
                                    res = "720p"

                                stream_name = f"[TR DUBLAJ] 🧲 Torrent {res}"
                                stream_title = f"{name}\n🔊 Türkçe Dublaj / Dual Audio | 💾 {size_gb} | 👤 Seeds: {seeds}"

                                streams.append(
                                    Stream(
                                        name=stream_name,
                                        title=stream_title,
                                        infoHash=info_hash
                                    )
                                )
                except Exception as e:
                    print(f"[{self.name}] Apibay error for {term}: {e}")

        return streams
