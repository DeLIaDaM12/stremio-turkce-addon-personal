 import re
 import urllib.parse
 from typing import List, Set, Tuple
 
 import httpx
 from bs4 import BeautifulSoup
 
 from app.extractors.generic_hls import GenericHlsExtractor
 from app.extractors.rapidrame import RapidrameExtractor
 from app.extractors.vidmoly import VidmolyExtractor
 from app.models import BehaviorHints, Stream, UserConfig
 from app.providers.base import BaseProvider
+from app.providers.utils import is_cloudflare_challenge, movie_match_score
 from app.services.metadata import MediaMeta
 
 
 class HdFilmCehennemiProvider(BaseProvider):
     name = "HDFilmCehennemi"
     is_torrent = False
     ACTIVE_MIRRORS = (
         "https://www.hdfilmcehennemi.ws",
         "https://www.hdfilmcehennemi.nl",
     )
     USER_AGENT = (
         "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
     )
 
     def __init__(self) -> None:
         self.vidmoly = VidmolyExtractor()
         self.rapidrame = RapidrameExtractor()
         self.generic_hls = GenericHlsExtractor()
 
     @staticmethod
     def _normalize_url(base_url: str, value: str) -> str:
         if not value:
             return ""
         value = value.strip().replace("\\/", "/")
@@ -43,87 +44,90 @@ class HdFilmCehennemiProvider(BaseProvider):
 
     @staticmethod
     def _slug(value: str) -> str:
         value = value.casefold().replace("&", " and ")
         value = re.sub(r"[^a-z0-9]+", "-", value)
         return value.strip("-")
 
     def _direct_title_urls(self, meta: MediaMeta, base_url: str) -> List[str]:
         values = [meta.original_title, meta.turkish_title]
         urls: List[str] = []
         seen: Set[str] = set()
         for value in values:
             if not value:
                 continue
             slug = self._slug(value)
             if not slug:
                 continue
             url = f"{base_url.rstrip('\''/'\'')}/{slug}/"
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
 
     def _search_candidates(self, html: str, meta: MediaMeta, base_url: str) -> List[str]:
         soup = BeautifulSoup(html, "html.parser")
         selectors = (
             ".poster.poster-pop, .card-body a, .poster-media, article a, "
             ".film-list a, .film-item a, a.film-link, a[href*='\''/film/'\''], "
             "a[href*='\''/dizi/'\''], a[href*='\''/series/'\'']"
         )
-        candidates: List[str] = []
+        candidates: List[Tuple[int, str]] = []
         seen: Set[str] = set()
 
         for node in soup.select(selectors):
             link = node if node.name == "a" else node.find("a")
             if not link:
                 continue
             url = self._normalize_url(base_url, link.get("href", ""))
             if not url or url in seen:
                 continue
             label = link.get("title") or link.get_text(" ", strip=True) or node.get_text(" ", strip=True)
-            if meta.year and not self._title_matches(label, meta):
+            if not self._title_matches(label, meta):
                 continue
             seen.add(url)
             if meta.media_type == "series" and meta.season and meta.episode:
                 suffix = f"-{meta.season}-sezon-{meta.episode}-bolum"
                 if not url.rstrip("/").casefold().endswith(suffix.casefold()):
                     url = f"{url.rstrip('\''/'\'')}{suffix}/"
-            candidates.append(url)
-        return candidates
+            score = movie_match_score(label, meta) or 0 if meta.media_type == "movie" else 0
+            candidates.append((score, url))
+        return [url for _, url in sorted(candidates, key=lambda item: item[0], reverse=True)]
 
     @staticmethod
     def _audio_type(label: str, url: str) -> str:
         text = f"{label} {url}".casefold()
         if any(value in text for value in ("dublaj", "dub", "türkçe ses", "turkce ses")):
             return "Türkçe Dublaj"
         if any(value in text for value in ("altyazi", "alt yaz", "subtitle")):
             return "Türkçe Altyazı"
         return "Türkçe Dublaj"
 
     def _collect_players(self, html: str, page_url: str) -> List[Tuple[str, str]]:
         soup = BeautifulSoup(html, "html.parser")
         selectors = (
             "nav.nav-tab a, .nav-tabs a, button[data-bs-target], a[data-frame], "
             "a[data-src], a[data-url], a[href*='\''/player/'\''], iframe, video source, source"
         )
         players: List[Tuple[str, str]] = []
         seen: Set[str] = set()
 
         for node in soup.select(selectors):
             raw_url = (
                 node.get("data-frame") or node.get("data-src") or node.get("data-url")
                 or node.get("src") or node.get("href")
             )
             url = self._normalize_url(page_url, raw_url or "")
@@ -155,91 +159,91 @@ class HdFilmCehennemiProvider(BaseProvider):
     @staticmethod
     def _diagnostic(response: httpx.Response) -> str:
         title = BeautifulSoup(response.text, "html.parser").title
         page_title = title.get_text(" ", strip=True) if title else ""
         return f"status={response.status_code} url={response.url} bytes={len(response.content)} title={page_title!r}"
 
     async def get_streams(self, meta: MediaMeta, config: UserConfig) -> List[Stream]:
         headers = {"User-Agent": self.USER_AGENT, "Referer": self.ACTIVE_MIRRORS[0]}
         streams: List[Stream] = []
         seen_streams: Set[str] = set()
 
         async with httpx.AsyncClient(
             headers=headers,
             timeout=httpx.Timeout(8.0, connect=5.0),
             follow_redirects=True,
             verify=False,
         ) as client:
             target_url = ""
             for base_url in self.ACTIVE_MIRRORS:
                 # Prefer the site'\''s canonical title slug. The old /search/{query}
                 # route is not a reliable endpoint on this site.
                 direct_urls = self._direct_title_urls(meta, base_url)
                 for candidate in direct_urls:
                     try:
                         page = await client.get(candidate)
-                        players = self._collect_players(page.text, candidate) if page.status_code == 200 else []
+                        players = self._collect_players(page.text, candidate) if page.status_code == 200 and not is_cloudflare_challenge(page) else []
                         print(f"[{self.name}] direct {self._diagnostic(page)} players={len(players)}")
                         if players:
                             target_url = candidate
                             break
                     except httpx.HTTPError as exc:
                         print(f"[{self.name}] direct error url={candidate}: {exc}")
                 if target_url:
                     break
 
                 # Keep search only as a fallback, using the site'\''s actual route.
                 for query in meta.search_queries:
                     try:
                         search_url = f"{base_url}/?s={urllib.parse.quote(query)}"
                         response = await client.get(search_url)
                         print(f"[{self.name}] fallback search {self._diagnostic(response)} query={query!r}")
-                        if response.status_code != 200:
+                        if response.status_code != 200 or is_cloudflare_challenge(response):
                             continue
                         candidates = self._search_candidates(response.text, meta, base_url)
                         print(f"[{self.name}] fallback candidates={len(candidates)}")
                         for candidate in candidates[:10]:
                             page = await client.get(candidate)
-                            players = self._collect_players(page.text, candidate) if page.status_code == 200 else []
+                            players = self._collect_players(page.text, candidate) if page.status_code == 200 and not is_cloudflare_challenge(page) else []
                             print(f"[{self.name}] candidate {self._diagnostic(page)} players={len(players)}")
                             if players:
                                 target_url = candidate
                                 break
                         if target_url:
                             break
                     except httpx.HTTPError as exc:
                         print(f"[{self.name}] fallback search error query={query!r}: {exc}")
                 if target_url:
                     break
 
             if not target_url:
                 print(f"[{self.name}] no playable target found")
                 return streams
 
             try:
                 response = await client.get(target_url)
-                if response.status_code != 200:
+                if response.status_code != 200 or is_cloudflare_challenge(response):
                     print(f"[{self.name}] target rejected {self._diagnostic(response)}")
                     return streams
 
                 limit = max(0, config.max_streams_per_provider)
                 players = self._collect_players(response.text, target_url)
                 print(f"[{self.name}] target players={len(players)} url={target_url}")
                 for player_url, audio_type in players[:limit or None]:
                     try:
                         extracted = await self._extract_player(player_url, target_url)
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
                         name=f"[TR DUBLAJ] ⚡ {self.name}" if audio_type == "Türkçe Dublaj" else f"[TR ALTYAZI] ⚡ {self.name}",
                         title=f"{meta.original_title}\n🔊 {audio_type} | 🎬 {quality} | HLS Stream",
                         url=stream_url,
                         behaviorHints=BehaviorHints(proxyHeaders=extracted.get("headers") or {"Referer": target_url, "User-Agent": self.USER_AGENT}),
