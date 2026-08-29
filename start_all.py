import subprocess
import time
import os
import sys
import re

# Force UTF-8 stdout
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

CLOUDFLARED_PATHS = [
    r"C:\Program Files (x86)\cloudflared\cloudflared.exe",
    r"C:\Program Files\cloudflared\cloudflared.exe",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloudflared.exe"),
    "cloudflared.exe",
    "cloudflared",
]

def get_cloudflared_path():
    for p in CLOUDFLARED_PATHS:
        if os.path.exists(p):
            return p
    return None

def kill_existing():
    subprocess.run(
        ["powershell", "-Command",
         "Stop-Process -Name 'python','cloudflared' -Force -ErrorAction SilentlyContinue"],
        capture_output=True
    )
    time.sleep(1)

if __name__ == "__main__":
    kill_existing()

    cloudflared_bin = get_cloudflared_path()

    print("================================================================", flush=True)
    print("    STREMIO TURKCE DUBLAJ & SINEMA ADDON BASLATILIYOR", flush=True)
    print("================================================================", flush=True)
    print("\n[1/2] Yerel sunucu baslatiliyor (Port 7000)...", flush=True)

    # Start FastAPI server
    server_proc = subprocess.Popen(
        [sys.executable, "run.py"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=os.path.dirname(os.path.abspath(__file__))
    )
    time.sleep(3)  # bekle, sunucu hazir olsun

    https_url = None

    if cloudflared_bin:
        print("[2/2] Guvenli HTTPS Tunnel (Cloudflare) kuruluyor...", flush=True)
        tunnel_proc = subprocess.Popen(
            [cloudflared_bin, "tunnel", "--url", "http://localhost:7000"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='ignore',
            cwd=os.path.dirname(os.path.abspath(__file__))
        )

        start_time = time.time()
        while time.time() - start_time < 30:
            line = tunnel_proc.stdout.readline()
            if not line:
                time.sleep(0.1)
                continue
            m = re.search(r'(https://[a-zA-Z0-9\-]+\.trycloudflare\.com)', line)
            if m:
                https_url = m.group(1)
                break
    else:
        tunnel_proc = None
        print("[!] cloudflared bulunamadi, yerel ag uzerinden devam ediliyor.", flush=True)

    import socket
    def get_lan_ip():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    lan_ip = get_lan_ip()

    print("\n================================================================", flush=True)
    print("  EKLENTI BASARIYLA CALISIYOR!", flush=True)
    print("================================================================", flush=True)

    if https_url:
        print(f"\n>> STREMIO MANIFEST LINKI (TV + MOBIL + PC):", flush=True)
        print(f"   {https_url}/manifest.json", flush=True)
        print(f"\n>> KURULUM WEB SAYFASI:", flush=True)
        print(f"   {https_url}", flush=True)
    else:
        print(f"\n>> STREMIO MANIFEST LINKI (SADECE AYNI AG):", flush=True)
        print(f"   http://{lan_ip}:7000/manifest.json", flush=True)

    print("\n----------------------------------------------------------------", flush=True)
    print("NASIL EKLENIR?", flush=True)
    print(" 1. Stremio apin -> Eklentiler (Addons) -> Eklenti Ara kutusuna", flush=True)
    print("    yukardaki MANIFEST LINKINI yapistirin.", flush=True)
    print(" 2. 'Install' butonuna basin.", flush=True)
    print(" 3. Hesabiniza eklenir, TV'nize otomatik gelir!", flush=True)
    print("================================================================\n", flush=True)
    print("[*] Kapatmak icin bu pencereyi kapatin veya CTRL+C basin.", flush=True)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server_proc.terminate()
        if tunnel_proc:
            tunnel_proc.terminate()
