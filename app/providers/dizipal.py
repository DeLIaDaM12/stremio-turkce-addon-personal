import re
import urllib.parse
from typing import List, Set

import httpx
from bs4 import BeautifulSoup

from app.models import Stream, UserConfig, BehaviorHints
from app.providers.base import BaseProvider
from app.services.metadata import MediaMeta
from app.extractors.generic_hls import GenericHlsExtractor
from app.extractors.vidmoly import VidmolyExtractor


class DizipalProvider(BaseProvider):
    name = "Dizipal"
    is_torrent = False
    BASE_URL = "https://dizipalw.com"  # Active mirror

    def __init__(self):
        self.generic_hls = GenericHlsExtractor()
        self.vidmoly = VidmolyExtractor()

    @staticmethod
    def _normalize_url(base_url: str, href: str) -> str:
        if not href:
            return ""

        href = href.strip()
        if href.startswith("http://") or href.startswith("https://"):
            return href
        if href.startswith("//"):
            return "https:" + href
        return urllib.parse.urljoin(base_url.rstrip("/") + "/", href)

    @staticmethod
    def _text_matches_title(title_text: str, meta: MediaMeta) -> bool:
        if not title_text:
            return True

        title = title_text.lower()
        if meta.original_title and meta.original_title.lower() in title:
            return True
        if meta.turkish_title and meta.turkish_title.lower() in title:
            return True

        if meta.year:
            year = str(meta.year)
            if year in title:
                return True
            for offset in (-1, 1):
                if str(meta.year + offset) in title:
                    return True

        return False

    def _candidate_links(self, soup: BeautifulSoup, meta: MediaMeta, base_url: str) -> List[str]:
        candidates: List[str] = []
        seen: Set[str] = set()

        selectors = [
            "article a",
            ".search-result a",
            ".movies-list a",
            ".film a",
            ".movie a",
            "a[href*='/film/']",
            "a[href*='/dizi/']",
            "a[href*='/series/']",
        ]

        for node in soup.select(",".join(selectors)):
            href = node.get("href")
            if not href:
                continue

            full_url = self._normalize_url(base_url, href)
            if not full_url or full_url in seen:
                continue
            seen.add(full_url)

            title_text = node.get("title") or node.get_text(" ", strip=True) or ""
            if meta.year and not self._text_matches_title(title_text, meta):
                continue

            if meta.media_type == "series" and meta.season and meta.episode:
                if full_url.rstrip("/").endswith(f"-{meta.season}-sezon-{meta.episode}"):
                    candidates.append(full_url)
                    continue
                candidates.append(f"{full_url.rstrip('/')}-sezon-{meta.season}-bolum-{meta.episode}")
            else:
                candidates.append(full_url)

        return candidates

    async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
        streams: List[Stream] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Referer": self.BASE_URL,
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
                    candidates = self._candidate_links(soup, meta, self.BASE_URL)

                    for candidate in candidates[:10]:
                        try:
                            page_resp = await client.get(candidate)
                            if page_resp.status_code != 200:
                                continue

                            page_html = page_resp.text
                            page_soup = BeautifulSoup(page_html, "html.parser")

                            # Quick content sanity check to avoid picking unrelated results
                            title_text = (page_soup.title.get_text(" ", strip=True) if page_soup.title else "")
                            if meta.original_title and meta.original_title.lower() not in title_text.lower():
                                # not an exact title match, but still allow near matches if we have a player
                                if not any(tag.get("src") and ".m3u8" in (tag.get("src") or "").lower() for tag in page_soup.select("iframe, source, script, a")):
                                    continue

                            target_url = candidate
                            break
                        except Exception as exc:
                            print(f"[{self.name}] Candidate fetch error for {candidate}: {exc}")

                    if target_url:
                        break

                except Exception as exc:
                    print(f"[{self.name}] Search error for query '{query}': {exc}")

            if not target_url:
                return streams

            try:
                page_resp = await client.get(target_url)
                if page_resp.status_code != 200:
                    return streams

                page_html = page_resp.text
                page_soup = BeautifulSoup(page_html, "html.parser")

                stream_urls: Set[str] = set()

                # Direct m3u8 URLs in iframe/source/script blocks
                for tag in page_soup.select("iframe, source, script, a[href*='.m3u8'], a[href*='playlist']"):
                    for attr_name in ("src", "data-src", "href"):
                        raw = tag.get(attr_name)
                        if not raw:
                            continue
                        if ".m3u8" in raw.lower():
                            stream_urls.add(self._normalize_url(target_url, raw))

                # Regex fallback for embedded HLS URLs
                for match in re.findall(r'"?(https?://[^"\'\s>]+\.m3u8[^"\'\s>]*)"?', page_html):
                    stream_urls.add(match)

                for stream_url in sorted(stream_urls):
                    if not stream_url:
                        continue

                    extracted = None
                    if "vidmoly" in stream_url.lower():
                        extracted = await self.vidmoly.extract(stream_url, referer=target_url)
                    elif stream_url.lower().endswith(".m3u8"):
                        extracted = {"url": stream_url, "quality": "1080p", "headers": {"Referer": target_url, "User-Agent": headers["User-Agent"]}}

                    if not extracted or not extracted.get("url"):
                        continue

                    quality = extracted.get("quality") or "1080p"
                    stream_name = f"[TR DUBLAJ] ⚡ {self.name}"
                    stream_title = f"{meta.original_title}\n🔊 Türkçe Dublaj | 🎬 {quality} | HLS Stream"

                    streams.append(
                        Stream(
                            name=stream_name,
                            title=stream_title,
                            url=extracted["url"],
                            behaviorHints=BehaviorHints(
                                proxyHeaders=extracted.get("headers") or {
                                    "Referer": target_url,
                                    "User-Agent": headers["User-Agent"],
                                }
                            ),
                        )
                    )

            except Exception as exc:
                print(f"[{self.name}] Stream extraction error: {exc}")

        return streams
