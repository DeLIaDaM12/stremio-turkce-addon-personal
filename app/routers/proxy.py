import base64
import urllib.parse
import httpx
from fastapi import APIRouter, Request, Response, HTTPException
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/proxy", tags=["Proxy"])

@router.get("/stream")
async def proxy_stream(
    url: str,
    referer: str = "",
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
):
    """Proxies HLS (.m3u8, .ts) and MP4 video streams adding required Referer and User-Agent headers."""
    decoded_url = urllib.parse.unquote(url)
    if not decoded_url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid stream URL")

    headers = {
        "User-Agent": user_agent,
    }
    if referer:
        headers["Referer"] = referer

    async def stream_generator():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            async with client.stream("GET", decoded_url, headers=headers) as resp:
                async for chunk in resp.aiter_bytes(chunk_size=65536):
                    yield chunk

    # If it is an M3U8 manifest, we can also fetch and rewrite if needed
    if ".m3u8" in decoded_url:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(decoded_url, headers=headers)
            content_type = resp.headers.get("content-type", "application/vnd.apple.mpegurl")
            
            # Return with permissive CORS for all TV & Web players
            return Response(
                content=resp.content,
                media_type=content_type,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Access-Control-Allow-Headers": "*"
                }
            )

    return StreamingResponse(
        stream_generator(),
        media_type="video/mp4",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*"
        }
    )
