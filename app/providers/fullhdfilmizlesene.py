 (cd "$(git rev-parse --show-toplevel)" && printf '%s' 'diff --git a/app/providers/fullhdfilmizlesene.py b/app/providers/fullhdfilmizlesene.py
index 67889aafc5c8632386f01f2cbddd8dcffeb6b5e9..4361653e9da5b2061dab239af5e176f811c25ecb 100644
--- a/app/providers/fullhdfilmizlesene.py
+++ b/app/providers/fullhdfilmizlesene.py
@@ -1,36 +1,37 @@
 import re
 import urllib.parse
 from typing import List, Set
 
 import httpx
 from bs4 import BeautifulSoup
 
 from app.extractors.generic_hls import GenericHlsExtractor
 from app.extractors.vidmoly import VidmolyExtractor
 from app.models import BehaviorHints, Stream, UserConfig
 from app.providers.base import BaseProvider
+from app.providers.utils import is_cloudflare_challenge, movie_match_score
 from app.services.metadata import MediaMeta
 
 
 class FullHdFilmizleseneProvider(BaseProvider):
     name = "FullHDFilmizlesene"
     is_torrent = False
     BASE_URL = "https://www.fullhdfilmizlesene.pw"
     USER_AGENT = (
         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
         "AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/124.0.0.0 Safari/537.36"
     )
 
     def __init__(self) -> None:
         self.generic_hls = GenericHlsExtractor()
         self.vidmoly = VidmolyExtractor()
 
     @staticmethod
     def _normalize_url(base_url: str, value: str) -> str:
         if not value:
             return ""
         value = value.strip().replace("\\/", "/")
         if value.startswith(("javascript:", "mailto:", "#")):
             return ""
         if value.startswith("//"):
@@ -46,50 +47,52 @@ class FullHdFilmizleseneProvider(BaseProvider):
         urls: List[str] = []
         seen: Set[str] = set()
         for title in (meta.original_title, meta.turkish_title):
             if not title:
                 continue
             slug = self._slug(title)
             if not slug:
                 continue
             base = f"{self.BASE_URL}/{slug}"
             variants = [base]
             if meta.media_type == "series" and meta.season and meta.episode:
                 variants = [
                     f"{base}-{meta.season}-sezon-{meta.episode}-bolum",
                     f"{base}-sezon-{meta.season}-bolum-{meta.episode}",
                     base,
                 ]
             for value in variants:
                 url = value.rstrip("/") + "/"
                 if url not in seen:
                     seen.add(url)
                     urls.append(url)
         return urls
 
     @staticmethod
     def _title_matches(text: str, meta: MediaMeta) -> bool:
+        if meta.media_type == "movie":
+            return movie_match_score(text, meta) is not None
         if not text:
             return True
         title = text.casefold()
         names = [value.casefold() for value in (meta.original_title, meta.turkish_title) if value]
         if not names:
             return True
         if any(name in title for name in names):
             return True
         return bool(meta.year and any(str(meta.year + offset) in title for offset in (-1, 0, 1)))
 
     def _player_urls(self, html: str, page_url: str) -> List[str]:
         soup = BeautifulSoup(html, "html.parser")
         urls: List[str] = []
         seen: Set[str] = set()
 
         def add(value: str) -> None:
             url = self._normalize_url(page_url, value)
             if url and url not in seen:
                 seen.add(url)
                 urls.append(url)
 
         for node in soup.select(
             "iframe, embed, video, source, script, a[data-src], a[data-frame], "
             "a[data-url], a[href*='\''/player/'\''], a[href*='\''embed'\'']"
         ):
@@ -115,101 +118,103 @@ class FullHdFilmizleseneProvider(BaseProvider):
     def _diagnostic(response: httpx.Response) -> str:
         title = BeautifulSoup(response.text, "html.parser").title
         page_title = title.get_text(" ", strip=True) if title else ""
         return f"status={response.status_code} url={response.url} bytes={len(response.content)} title={page_title!r}"
 
     async def _extract(self, url: str, referer: str):
         if "vidmoly" in url.casefold():
             return await self.vidmoly.extract(url, referer=referer)
         return await self.generic_hls.extract(url, referer=referer)
 
     async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
         headers = {"User-Agent": self.USER_AGENT, "Referer": self.BASE_URL}
         streams: List[Stream] = []
         seen_streams: Set[str] = set()
 
         async with httpx.AsyncClient(
             headers=headers,
             timeout=httpx.Timeout(8.0, connect=5.0),
             follow_redirects=True,
             verify=False,
         ) as client:
             target_url = ""
             for candidate in self._direct_title_urls(meta):
                 try:
                     page = await client.get(candidate)
-                    players = self._player_urls(page.text, candidate) if page.status_code == 200 else []
+                    players = self._player_urls(page.text, candidate) if page.status_code == 200 and not is_cloudflare_challenge(page) else []
                     print(f"[{self.name}] direct {self._diagnostic(page)} players={len(players)}")
                     if players:
                         target_url = candidate
                         break
                 except httpx.HTTPError as exc:
                     print(f"[{self.name}] direct error url={candidate}: {exc}")
 
             if not target_url:
                 for query in meta.search_queries:
                     try:
                         search_url = f"{self.BASE_URL}/?s={urllib.parse.quote(query)}"
                         response = await client.get(search_url)
                         print(f"[{self.name}] fallback search {self._diagnostic(response)} query={query!r}")
-                        if response.status_code != 200:
+                        if response.status_code != 200 or is_cloudflare_challenge(response):
                             continue
                         soup = BeautifulSoup(response.text, "html.parser")
-                        candidates: List[str] = []
+                        candidates: List[tuple[int, str]] = []
                         seen_candidates: Set[str] = set()
                         for node in soup.select(
                             ".film-list a, .film-item a, a.film-link, .movie a, "
                             ".card a, .item a, article a, a[rel='\''bookmark'\'']"
                         ):
                             candidate = self._normalize_url(self.BASE_URL, node.get("href", ""))
                             if not candidate or candidate in seen_candidates:
                                 continue
                             label = node.get("title") or node.get_text(" ", strip=True)
-                            if meta.year and not self._title_matches(label, meta):
+                            if not self._title_matches(label, meta):
                                 continue
                             seen_candidates.add(candidate)
-                            candidates.append(candidate)
+                            score = movie_match_score(label, meta) or 0 if meta.media_type == "movie" else 0
+                            candidates.append((score, candidate))
+                        candidates.sort(key=lambda item: item[0], reverse=True)
                         print(f"[{self.name}] fallback candidates={len(candidates)}")
-                        for candidate in candidates[:10]:
+                        for _, candidate in candidates[:10]:
                             page = await client.get(candidate)
-                            players = self._player_urls(page.text, candidate) if page.status_code == 200 else []
+                            players = self._player_urls(page.text, candidate) if page.status_code == 200 and not is_cloudflare_challenge(page) else []
                             print(f"[{self.name}] candidate {self._diagnostic(page)} players={len(players)}")
                             if players:
                                 target_url = candidate
                                 break
                         if target_url:
                             break
                     except httpx.HTTPError as exc:
                         print(f"[{self.name}] fallback search error query={query!r}: {exc}")
 
             if not target_url:
                 print(f"[{self.name}] no playable target found")
                 return streams
 
             try:
                 page = await client.get(target_url)
-                if page.status_code != 200:
+                if page.status_code != 200 or is_cloudflare_challenge(page):
                     print(f"[{self.name}] target rejected {self._diagnostic(page)}")
                     return streams
                 player_urls = self._player_urls(page.text, target_url)
                 print(f"[{self.name}] target players={len(player_urls)} url={target_url}")
                 limit = max(0, config.max_streams_per_provider)
                 for player_url in player_urls[:limit or None]:
                     try:
                         extracted = await self._extract(player_url, target_url)
                     except Exception as exc:
                         print(f"[{self.name}] extraction error url={player_url}: {type(exc).__name__}: {exc}")
                         continue
                     if not extracted or not extracted.get("url"):
                         print(f"[{self.name}] extractor returned no media url={player_url}")
                         continue
                     stream_url = extracted["url"]
                     if stream_url in seen_streams:
                         continue
                     seen_streams.add(stream_url)
                     quality = extracted.get("quality") or "1080p"
                     streams.append(Stream(
                         name=f"[TR DUBLAJ] ⚡ {self.name}",
                         title=f"{meta.original_title}\n🔊 Türkçe Dublaj | 🎬 {quality} | HLS Stream",
                         url=stream_url,
                         behaviorHints=BehaviorHints(
                             proxyHeaders=extracted.get("headers") or {
' | git apply --3way)
