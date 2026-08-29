import json
import base64
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.models import UserConfig
from app.config import settings

router = APIRouter(tags=["Manifest"])

MANIFEST_DATA = {
    "id": "community.turkce.dublaj",
    "version": "1.0.0",
    "name": "Turkce Dublaj & Sinema",
    "description": "Stremio icin Turkce Dublaj ve Altyazili yerli kaynaklar (Direkt Akis ve Torrent)",
    "resources": [
        "stream"
    ],
    "types": ["movie", "series", "anime"],
    "idPrefixes": ["tt"],
    "catalogs": [],
    "behaviorHints": {
        "configurable": True,
        "configurationRequired": False
    },
    "background": "https://images.unsplash.com/photo-1517604931442-7e0c8ed2963c?q=80&w=1920&auto=format&fit=crop",
    "logo": "https://img.icons8.com/fluency/96/turkish-flag.png"
}

def decode_config(config_str: str) -> UserConfig:
    try:
        data = json.loads(base64.b64decode(config_str).decode("utf-8"))
        return UserConfig(**data)
    except Exception:
        return UserConfig()

@router.get("/manifest.json")
async def default_manifest():
    return JSONResponse(
        content=MANIFEST_DATA,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Content-Type": "application/json; charset=utf-8"
        }
    )

@router.get("/{config}/manifest.json")
async def custom_manifest(config: str):
    return JSONResponse(
        content=MANIFEST_DATA,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
            "Content-Type": "application/json; charset=utf-8"
        }
    )
