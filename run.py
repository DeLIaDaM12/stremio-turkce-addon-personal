import uvicorn
import os
import sys
import socket

# Force UTF-8 stdout on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config import settings

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

if __name__ == "__main__":
    port = int(os.environ.get("PORT", settings.PORT))
    local_ip = get_local_ip()

    print("==================================================")
    print("[+] Stremio Turkce Dublaj & Altyazi Eklentisi")
    print("==================================================")
    print(f"[*] PC Panel:            http://localhost:{port}")
    print(f"[*] TV & Ag Linki (LAN): http://{local_ip}:{port}")
    print(f"[*] Manifest (TV Uyumlu):http://{local_ip}:{port}/manifest.json")
    print("--------------------------------------------------")
    print("[!] ONEMLI: TV'den izlerken eklentiyi Stremio'ya")
    print(f"    'http://{local_ip}:{port}/manifest.json' linkiyle ekleyin.")
    print("==================================================\n")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)
