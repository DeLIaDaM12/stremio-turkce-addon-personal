import re
import httpx
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from app.services.cache import CacheService, metadata_cache

class MediaMeta(BaseModel):
    imdb_id: str
    media_type: str  # "movie" or "series"
    original_title: str
    turkish_title: Optional[str] = None
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_title: Optional[str] = None
    search_queries: List[str] = []

class MetadataService:
    CINEMETA_URL = "https://v3-cinemeta.strem.io/meta/{type}/{id}.json"

    @classmethod
    async def resolve(cls, media_type: str, raw_id: str) -> Optional[MediaMeta]:
        """Resolves Stremio ID (e.g. tt1234567 or tt1234567:1:1) to MediaMeta with Turkish and Original titles."""
        cache_key = CacheService.generate_key("meta", media_type, raw_id)
        cached = CacheService.get(metadata_cache, cache_key)
        if cached:
            return cached

        # Parse ID components
        parts = raw_id.split(":")
        imdb_id = parts[0]
        season = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
        episode = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None

        # Fetch Cinemeta metadata
        url = cls.CINEMETA_URL.format(type=media_type, id=imdb_id)
        
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return None
                data = resp.json()
                meta_dict = data.get("meta")
                if not meta_dict:
                    return None
                
                name = meta_dict.get("name", "")
                year_raw = meta_dict.get("year", "")
                year = None
                if year_raw:
                    m = re.search(r"\b(19\d{2}|20\d{2})\b", str(year_raw))
                    if m:
                        year = int(m.group(1))
                
                # Try to get Turkish title from TMDB / Free endpoint or Cinemeta translations
                turkish_title = await cls._fetch_turkish_title(client, imdb_id, media_type) or name

                # Generate clean search variations
                queries = cls._generate_queries(name, turkish_title)

                media_meta = MediaMeta(
                    imdb_id=imdb_id,
                    media_type=media_type,
                    original_title=name,
                    turkish_title=turkish_title,
                    year=year,
                    season=season,
                    episode=episode,
                    search_queries=queries
                )

                CacheService.set(metadata_cache, cache_key, media_meta)
                return media_meta
            except Exception as e:
                print(f"[MetadataService] Error resolving {raw_id}: {e}")
                return None

    @classmethod
    async def _fetch_turkish_title(cls, client: httpx.AsyncClient, imdb_id: str, media_type: str) -> Optional[str]:
        """Queries TMDB find endpoint or Cinemeta TR to fetch Turkish localized title."""
        try:
            # Using TMDB public find lookup
            find_url = f"https://api.themoviedb.org/3/find/{imdb_id}?external_source=imdb_id&language=tr-TR&api_key=1b50ba0e0b992030e482632ecd405976"
            resp = await client.get(find_url)
            if resp.status_code == 200:
                data = resp.json()
                if media_type == "movie":
                    results = data.get("movie_results", [])
                    if results and results[0].get("title"):
                        return results[0]["title"]
                elif media_type == "series":
                    results = data.get("tv_results", [])
                    if results and results[0].get("name"):
                        return results[0]["name"]
        except Exception:
            pass
        return None

    @staticmethod
    def _generate_queries(original_title: str, turkish_title: Optional[str]) -> List[str]:
        queries = []
        if turkish_title:
            cleaned_tr = re.sub(r"[^\w\s]", " ", turkish_title).strip()
            queries.append(turkish_title)
            if cleaned_tr != turkish_title:
                queries.append(cleaned_tr)
        
        if original_title and original_title not in queries:
            cleaned_orig = re.sub(r"[^\w\s]", " ", original_title).strip()
            queries.append(original_title)
            if cleaned_orig != original_title:
                queries.append(cleaned_orig)
                
        return list(dict.fromkeys(queries))  # Remove duplicates preserving order
