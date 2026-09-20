import html
import re
from typing import Any, Dict, Optional

import httpx

from app.extractors.base import BaseExtractor


class VidmolyExtractor(BaseExtractor):
    name = "VidMoly"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    URL_PATTERN = re.compile(
        r"(?:https?:)?//[^\"'<>\s\\]+?\.(?:m3u8|mp4)(?:\?[^\"'<>\s\\]*)?",
        re.IGNORECASE,
    )

    @classmethod
    def _find_media_url(cls, content: str) -> Optional[str]:
        content = html.unescape(content).replace("\\/", "/")
        patterns = (
            r"(?:file|src|source|hls|playlist|url)\s*:\s*[\"']([^\"']+)",
            r"(?:file|src|source|hls|playlist|url)\s*=\s*[\"']([^\"']+)",
        )
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match and (".m3u8" in match.group(1).lower() or ".mp4" in match.group(1).lower()):
                return match.group(1)

        match = cls.URL_PATTERN.search(content)
        return match.group(0) if match else None

    async def extract(
        self,
        embed_url: str,
        referer: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        headers = {
            "User-Agent": self.USER_AGENT,
            "Referer": referer or "https://vidmoly.to/",
        }

        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(10.0, connect=5.0),
                follow_redirects=True,
                verify=True,
            ) as client:
                response = await client.get(embed_url)
                if response.status_code >= 400:
                    return None

                content = response.text
                if "eval(function(p,a,c,k,e,d)" in content:
                    content = self.unpack_packer(content)

                stream_url = self._find_media_url(content)
                if not stream_url:
                    return None

                if stream_url.startswith("//"):
                    stream_url = "https:" + stream_url
                elif stream_url.startswith("/"):
                    stream_url = str(response.url).rstrip("/") + stream_url

                return {
                    "url": stream_url,
                    "quality": "1080p",
                    "format": "hls" if ".m3u8" in stream_url.lower() else "mp4",
                    "headers": {
                        "Referer": str(response.url),
                        "User-Agent": self.USER_AGENT,
                    },
                }
        except (httpx.HTTPError, ValueError) as exc:
            print(f"[{self.name}] Error extracting {embed_url}: {exc}")

        return None
