import socket
import os
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader

templates_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
jinja_env = Environment(loader=FileSystemLoader(templates_dir), autoescape=True)

router = APIRouter(tags=["Configure"])

def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

@router.get("/", response_class=HTMLResponse)
@router.get("/configure", response_class=HTMLResponse)
async def configure_page(request: Request):
    local_ip = get_local_ip()
    port = request.url.port or 7000
    host_header = request.headers.get("host", f"localhost:{port}")
    
    # TV Base URL (using LAN IP so TV can reach PC over Wi-Fi)
    if "localhost" in host_header or "127.0.0.1" in host_header:
        tv_base_url = f"http://{local_ip}:{port}"
    else:
        tv_base_url = f"{request.url.scheme}://{host_header}"

    base_url = f"{request.url.scheme}://{host_header}"
    manifest_url = f"{tv_base_url}/manifest.json"
    stremio_install_url = f"stremio://{tv_base_url.replace('http://', '').replace('https://', '')}/manifest.json"

    template = jinja_env.get_template("index.html")
    content = template.render(
        request=request,
        base_url=base_url,
        tv_base_url=tv_base_url,
        local_ip=local_ip,
        manifest_url=manifest_url,
        stremio_install_url=stremio_install_url
    )
    return HTMLResponse(content=content)
