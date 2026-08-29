import urllib.parse
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.models import StreamResponse, UserConfig
from app.routers.manifest import decode_config
from app.services.metadata import MetadataService
from app.providers import fetch_all_streams

router = APIRouter(tags=["Stream"])

@router.get("/stream/{media_type}/{media_id}.json")
async def get_default_streams(media_type: str, media_id: str, request: Request):
    return await handle_stream_request(media_type, media_id, UserConfig(), request)

@router.get("/{config}/stream/{media_type}/{media_id}.json")
async def get_custom_streams(config: str, media_type: str, media_id: str, request: Request):
    user_config = decode_config(config)
    return await handle_stream_request(media_type, media_id, user_config, request)

async def handle_stream_request(media_type: str, media_id: str, config: UserConfig, request: Request) -> JSONResponse:
    clean_id = media_id.replace(".json", "")

    # Resolve metadata & Turkish translation
    meta = await MetadataService.resolve(media_type, clean_id)
    if not meta:
        return JSONResponse(
            content={"streams": []},
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "*"
            }
        )

    # Fetch streams from all providers
    streams = await fetch_all_streams(meta, config)

    # Process URLs: if stream has proxyHeaders, wrap with proxy URL
    base_url = str(request.base_url).rstrip("/")
    stream_dicts = []
    for s in streams:
        s_dict = s.model_dump(exclude_none=True)
        if s.url and s.behaviorHints and s.behaviorHints.proxyHeaders:
            referer = s.behaviorHints.proxyHeaders.get("Referer", "")
            ua = s.behaviorHints.proxyHeaders.get("User-Agent", "")
            proxy_url = f"{base_url}/proxy/stream?url={urllib.parse.quote(s.url)}&referer={urllib.parse.quote(referer)}&user_agent={urllib.parse.quote(ua)}"
            s_dict["url"] = proxy_url
            s_dict.pop("behaviorHints", None)
        stream_dicts.append(s_dict)

    return JSONResponse(
        content={"streams": stream_dicts},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*"
        }
    )
