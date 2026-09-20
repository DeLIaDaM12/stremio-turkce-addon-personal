import urllib.parse
from typing import List

import httpx

from app.models import Stream, UserConfig
from app.providers.base import BaseProvider
from app.services.metadata import MediaMeta


class TurkTorrentProvider(BaseProvider):
    name = "TurkTorrent"
    is_torrent = True
    API_URL = "https://apibay.org/q.php"

    @staticmethod
    def _quality(name: str) -> str:
        lower = name.casefold()
        if "2160p" in lower or "4k" in lower:
            return "4K 2160p"
        if "1080p" in lower:
            return "1080p"
        if "720p" in lower:
            return "720p"
        return "Unknown"

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        if not config.enable_torrents:
            return []
        title = meta.original_title or meta.turkish_title
        if not title:
            return []

        terms = [f"{title} dual", f"{title} turkish"]
        if meta.season and meta.episode:
            terms.insert(0, f"{title} S{meta.season:02d}E{meta.episode:02d} dual")
        if meta.turkish_title and meta.turkish_title != meta.original_title:
            terms.append(f"{meta.turkish_title} dublaj")

        streams: List[Stream] = []
        seen = set()
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient(headers=headers, timeout=6.0, follow_redirects=True) as client:
            for term in terms[:3]:
                try:
                    response = await client.get(self.API_URL, params={"q": term})
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, list):
                        continue
                    for item in data[:6]:
                        if not isinstance(item, dict):
                            continue
                        info_hash = str(item.get("info_hash") or "").strip().lower()
                        if not info_hash or len(info_hash) != 40 or info_hash == "0" * 40 or info_hash in seen:
                            continue
                        seen.add(info_hash)
                        name = str(item.get("name") or "Untitled")
                        size = int(item.get("size") or 0)
                        size_text = f"{size / 1024**3:.1f} GB" if size else "Unknown"
                        seeds = item.get("seeders") or 0
                        quality = self._quality(name)
                        streams.append(Stream(
                            name=f"[TR DUBLAJ] 🧲 Torrent {quality}",
                            title=f"{name}\n🔊 Türkçe Dublaj / Dual Audio | 💾 {size_text} | 👤 Seeds: {seeds}",
                            infoHash=info_hash,
                        ))
                except (httpx.HTTPError, ValueError, TypeError) as exc:
                    print(f"[{self.name}] Search error for '{term}': {exc}")
        return streams
