import re
import httpx
from typing import Optional, Dict, Any
from app.extractors.base import BaseExtractor

class GenericHlsExtractor(BaseExtractor):
    name = "DirectHLS"

    async def extract(self, embed_url: str, referer: Optional[str] = None) -> Optional[Dict[str, Any]]:
        # If url is already an m3u8 or mp4
        if ".m3u8" in embed_url or ".mp4" in embed_url:
            return {
                "url": embed_url,
                "quality": "1080p",
                "format": "hls" if ".m3u8" in embed_url else "mp4",
                "headers": {
                    "Referer": referer or "",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
                }
            }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": referer or embed_url
        }

        async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True) as client:
            try:
                resp = await client.get(embed_url)
                html = resp.text

                if "eval(function(p,a,c,k,e,d)" in html:
                    html = self.unpack_packer(html)

                # Search for m3u8 / mp4 in script / html
                m = re.search(r'["\'](https?://[^"\']+\.(?:m3u8|mp4)[^"\']*)["\']', html)
                if m:
                    stream_url = m.group(1)
                    return {
                        "url": stream_url,
                        "quality": "1080p",
                        "format": "hls" if ".m3u8" in stream_url else "mp4",
                        "headers": {
                            "Referer": referer or embed_url,
                            "User-Agent": headers["User-Agent"]
                        }
                    }
            except Exception as e:
                print(f"[GenericHlsExtractor] Error: {e}")
        return None
