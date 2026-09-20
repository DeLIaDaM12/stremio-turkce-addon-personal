import html
import re
import urllib.parse
from typing import Any, Dict, Optional

import httpx

from app.extractors.base import BaseExtractor


class GenericHlsExtractor(BaseExtractor):
    name = "DirectHLS"
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    MEDIA_PATTERN = re.compile(
        r"(?:https?:)?//[^\"'<>\s\\]+?\.(?:m3u8|mp4)(?:\?[^\"'<>\s\\]*)?",
        re.IGNORECASE,
    )
    ATTRIBUTE_PATTERN = re.compile(
        r"(?:file|src|source|url|playlist|hls|stream)\s*[:=]\s*[\"']([^\"']+)",
        re.IGNORECASE,
    )
    IFRAME_PATTERN = re.compile(
        r"<iframe[^>]+(?:src|data-src)=[\"']([^\"']+)[\"']",
        re.IGNORECASE,
    )

    @classmethod
    def _normalize_url(cls, base_url: str, value: str) -> str:
        value = html.unescape(value).replace("\\/", "/").strip()
        if value.startswith("//"):
            return "https:" + value
        return urllib.parse.urljoin(base_url, value)

    @classmethod
    def _find_media_urls(cls, content: str, base_url: str) -> list[str]:
        content = html.unescape(content).replace("\\/", "/")
        found: list[str] = []

        for match in cls.MEDIA_PATTERN.findall(content):
            found.append(cls._normalize_url(base_url, match))
        for match in cls.ATTRIBUTE_PATTERN.findall(content):
            if ".m3u8" in match.lower() or ".mp4" in match.lower():
                found.append(cls._normalize_url(base_url, match))

        result: list[str] = []
        seen: set[str] = set()
        for url in found:
            if url and url not in seen:
                seen.add(url)
                result.append(url)
        return result

    @classmethod
    def _result(cls, url: str, referer: str) -> Dict[str, Any]:
        is_hls = ".m3u8" in url.lower()
        return {
            "url": url,
            "quality": "1080p",
            "format": "hls" if is_hls else "mp4",
            "headers": {"Referer": referer, "User-Agent": cls.USER_AGENT},
        }

    async def extract(
        self,
        embed_url: str,
        referer: Optional[str] = None,
        _depth: int = 0,
    ) -> Optional[Dict[str, Any]]:
        if not embed_url or _depth > 2:
            return None

        embed_url = self._normalize_url(referer or embed_url, embed_url)
        if ".m3u8" in embed_url.lower() or ".mp4" in embed_url.lower():
            return self._result(embed_url, referer or embed_url)

        headers = {
            "User-Agent": self.USER_AGENT,
            "Referer": referer or embed_url,
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

                media_urls = self._find_media_urls(content, str(response.url))
                if media_urls:
                    return self._result(media_urls[0], referer or embed_url)

                # Many provider pages expose only another player iframe.
                for iframe_url in self.IFRAME_PATTERN.findall(content):
                    normalized = self._normalize_url(str(response.url), iframe_url)
                    result = await self.extract(
                        normalized,
                        referer=embed_url,
                        _depth=_depth + 1,
                    )
                    if result:
                        return result
        except (httpx.HTTPError, ValueError) as exc:
            print(f"[{self.name}] Error extracting {embed_url}: {exc}")

        return None
