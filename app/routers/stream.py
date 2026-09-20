import asyncio
import urllib.parse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.models import UserConfig
from app.providers import fetch_all_streams
from app.routers.manifest import decode_config
from app.services.metadata import MetadataService

router = APIRouter(tags=["Stream"])


@router.get("/stream/{media_type}/{media_id}.json")
async def get_default_streams(media_type: str, media_id: str, request: Request):
    return await handle_stream_request(media_type, media_id, UserConfig(), request)


@router.get("/{config}/stream/{media_type}/{media_id}.json")
async def get_custom_streams(config: str, media_type: str, media_id: str, request: Request):
    return await handle_stream_request(
        media_type, media_id, decode_config(config), request
    )


async def handle_stream_request(
    media_type: str, media_id: str, config: UserConfig, request: Request
) -> JSONResponse:
    clean_id = media_id.removesuffix(".json")
    print(
        f"[StreamRouter] request method={request.method} "
        f"path={request.url.path} type={media_type!r} id={clean_id!r}",
        flush=True,
    )

    try:
        meta = await asyncio.wait_for(
            MetadataService.resolve(media_type, clean_id), timeout=18.0
        )
    except asyncio.TimeoutError:
        print(f"[StreamRouter] metadata timeout id={clean_id!r}", flush=True)
        return JSONResponse(content={"streams": []}, status_code=200)
    except Exception as exc:
        print(
            f"[StreamRouter] metadata failure {type(exc).__name__}: {exc}",
            flush=True,
        )
        return JSONResponse(content={"streams": []}, status_code=200)

    if not meta:
        print(f"[StreamRouter] metadata unavailable id={clean_id!r}", flush=True)
        return JSONResponse(content={"streams": []}, status_code=200)

    print(
        f"[StreamRouter] metadata title={meta.original_title!r} "
        f"queries={meta.search_queries!r}",
        flush=True,
    )
    try:
        streams = await asyncio.wait_for(
            fetch_all_streams(meta, config), timeout=45.0
        )
    except asyncio.TimeoutError:
        print(f"[StreamRouter] provider aggregation timeout id={clean_id!r}", flush=True)
        streams = []
    except Exception as exc:
        print(
            f"[StreamRouter] provider aggregation failure "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        streams = []

    base_url = str(request.base_url).rstrip("/")
    stream_dicts = []
    for stream in streams:
        stream_dict = stream.model_dump(exclude_none=True)
        if stream.url and stream.behaviorHints and stream.behaviorHints.proxyHeaders:
            proxy_headers = stream.behaviorHints.proxyHeaders
            query = urllib.parse.urlencode(
                {
                    "url": stream.url,
                    "referer": proxy_headers.get("Referer", ""),
                    "user_agent": proxy_headers.get("User-Agent", ""),
                }
            )
            stream_dict["url"] = f"{base_url}/proxy/stream?{query}"
            stream_dict.pop("behaviorHints", None)
        stream_dicts.append(stream_dict)

    print(f"[StreamRouter] response streams={len(stream_dicts)}", flush=True)
    return JSONResponse(
        content={"streams": stream_dicts},
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        },
    )
