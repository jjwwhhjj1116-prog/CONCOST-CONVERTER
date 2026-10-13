"""
사내 PC 변환 엔진 런처
1) ENGINE_KEY를 넣고 FastAPI(uvicorn) 기동
2) cloudflared Quick Tunnel 기동 후 발급된 https URL 파싱
3) Cloudflare Pages의 /api/engine/register 에 URL 등록 (D1 저장)
터널 URL이 바뀌어도(재시작 시) 자동 재등록되므로 도메인이 없어도 동작한다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES_URL = "https://concost-total-converter.pages.dev"
PORT = 8000
TUNNEL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def load_engine_key() -> str:
    """.engine.env 에서 ENGINE_KEY 로드"""
    env_file = ROOT / ".engine.env"
    for line in env_file.read_text(encoding="ascii").splitlines():
        if line.startswith("ENGINE_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(".engine.env 에 ENGINE_KEY가 없습니다.")


def find_cloudflared() -> str:
    """PATH 또는 winget 기본 설치 위치에서 cloudflared 탐색"""
    found = shutil.which("cloudflared")
    if found:
        return found
    for cand in (
        Path(os.environ.get("ProgramFiles(x86)", "")) / "cloudflared" / "cloudflared.exe",
        Path(os.environ.get("ProgramFiles", "")) / "cloudflared" / "cloudflared.exe",
    ):
        if cand.exists():
            return str(cand)
    raise RuntimeError("cloudflared 를 찾을 수 없습니다. winget install Cloudflare.cloudflared")


def wait_health(timeout: float = 30) -> None:
    """로컬 엔진 기동 대기"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=2):
                return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("로컬 엔진(uvicorn)이 기동되지 않았습니다.")


def register(url: str, key: str) -> None:
    """터널 URL을 Pages(D1)에 등록"""
    req = urllib.request.Request(
        f"{PAGES_URL}/api/engine/register",
        data=json.dumps({"url": url}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-Engine-Key": key, "User-Agent": "concost-engine"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        print(f"[등록] {r.read().decode()}", flush=True)


def main() -> int:
    key = load_engine_key()
    env = {**os.environ, "ENGINE_KEY": key, "PYTHONIOENCODING": "utf-8"}

    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=ROOT, env=env,
    )
    wait_health()
    print(f"[엔진] 로컬 변환 엔진 기동: http://127.0.0.1:{PORT}", flush=True)

    tunnel = subprocess.Popen(
        [find_cloudflared(), "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{PORT}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="ignore",
    )
    registered = False
    try:
        assert tunnel.stdout is not None
        for line in tunnel.stdout:
            if not registered:
                m = TUNNEL_RE.search(line)
                if m:
                    url = m.group(0)
                    print(f"[터널] {url}", flush=True)
                    # DNS 전파 대기 후 등록
                    time.sleep(5)
                    register(url, key)
                    registered = True
                    print(f"[완료] 직원 접속 주소: {PAGES_URL}  (이 창을 닫으면 변환 불가)", flush=True)
    finally:
        tunnel.terminate()
        api.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
