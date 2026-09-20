import urllib.parse
from typing import List

import httpx

from app.models import Stream, UserConfig
from app.providers.base import BaseProvider
from app.services.metadata import MediaMeta


class TurkTorrentProvider(BaseProvider):
    name = "TurkTorrent"
    is_torrent = True

    @staticmethod
    def _quality_from_name(name: str) -> str:
        lower = name.lower()
        if "2160p" in lower or "4k" in lower:
            return "4K 2160p"
        if "1080p" in lower:
            return "1080p"
        if "720p" in lower:
            return "720p"
        return "1080p"

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        if not config.enable_torrents:
            return []

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        }

        search_terms = []
        title = meta.original_title or meta.turkish_title
        if title:
            if meta.media_type == "movie":
                search_terms.extend([
                    f"{title} dual",
                    f"{title} turkish",
                    f"{title} tr",
                ])
            else:
                if meta.season and meta.episode:
                    search_terms.extend([
                        f"{title} S{meta.season:02d}E{meta.episode:02d} dual",
                        f"{title} S{meta.season:02d} dual",
                    ])
                search_terms.append(f"{title} dual")

        if meta.turkish_title and meta.turkish_title != meta.original_title:
            search_terms.append(f"{meta.turkish_title} dublaj")

        streams: List[Stream] = []
        async with httpx.AsyncClient(headers=headers, timeout=6.0, follow_redirects=True) as client:
            for term in search_terms[:3]:
                try:
                    url = f"https://apibay.org/q.php?q={urllib.parse.quote(term)}"
                    response = await client.get(url)
                    if response.status_code != 200:
                        continue
                    payload = response.json()
                    if not isinstance(payload, list) or not payload:
                        continue
                    for item in payload[:4]:
                        if not isinstance(item, dict):
                            continue
                        name = item.get("name") or ""
                        info_hash = (item.get("info_hash") or "").lower().strip()
                        if not info_hash or info_hash == "0000000000000000000000000000000000000000":
                            continue
                        size_bytes = int(item.get("size") or 0)
                        size_gb = f"{size_bytes / (1024**3):.1f} GB" if size_bytes > 0 else ""
                        seeds = item.get("seeders") or "0"
                        quality = self._quality_from_name(name)
                        stream_name = f"[TR DUBLAJ] 🧲 Torrent {quality}"
                        stream_title = f"{name}\n🔊 Türkçe Dublaj / Dual Audio | 💾 {size_gb} | 👤 Seeds: {seeds}"
                        streams.append(
                            Stream(
                                name=stream_name,
                                title=stream_title,
                                infoHash=info_hash,
                            )
                        )
                except Exception as exc:
                    print(f"[{self.name}] Apibay error for '{term}': {exc}")

        return streams
