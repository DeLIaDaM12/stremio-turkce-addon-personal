import re
import base64
import json
import httpx
from typing import Optional, Dict, Any
from app.extractors.base import BaseExtractor

class RapidrameExtractor(BaseExtractor):
    name = "Rapidrame"

    async def extract(self, embed_url: str, referer: Optional[str] = None) -> Optional[Dict[str, Any]]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": referer or "https://rapidrame.com/"
        }
        
        async with httpx.AsyncClient(headers=headers, timeout=8.0, follow_redirects=True) as client:
            try:
                resp = await client.get(embed_url)
                html = resp.text
                
                if "eval(function(p,a,c,k,e,d)" in html:
                    html = self.unpack_packer(html)

                # Look for file: "..." or sources: [{file: "..."}]
                m = re.search(r'file:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', html)
                if not m:
                    m = re.search(r'["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', html)
                if not m:
                    m = re.search(r'source\s*=\s*["\'](https?://[^"\']+)["\']', html)

                if m:
                    stream_url = m.group(1)
                    return {
                        "url": stream_url,
                        "quality": "1080p",
                        "format": "hls",
                        "headers": {
                            "Referer": referer or "https://rapidrame.com/",
                            "User-Agent": headers["User-Agent"]
                        }
                    }
            except Exception as e:
                print(f"[RapidrameExtractor] Error: {e}")
        return None
