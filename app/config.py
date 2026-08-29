import os
from pydantic import BaseModel

class Settings(BaseModel):
    APP_NAME: str = "Stremio Türkçe Dublaj & Sinema"
    APP_ID: str = "org.stremio.turkce.dublaj"
    VERSION: str = "1.0.0"
    DESCRIPTION: str = "Stremio için Türkçe Dublaj, Türkçe Altyazı ve Dual Audio kaynaklarını (Direkt Video Akışları ve Torrent) bir araya getiren özel eklenti."
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "7000"))
    BASE_URL: str = os.getenv("BASE_URL", "")
    
    # Cache settings (seconds)
    METADATA_CACHE_TTL: int = 86400  # 24 hours
    STREAMS_CACHE_TTL: int = 3600    # 1 hour
    
    # Request timeouts (seconds)
    SCRAPER_TIMEOUT: float = 8.0

settings = Settings()
