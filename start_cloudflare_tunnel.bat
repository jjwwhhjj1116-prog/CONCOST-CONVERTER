@echo off
chcp 65001 > nul
echo ========================================================
echo   CONCOST Cloudflare Quick Tunnel 실행기 (외부 배포용)
echo ========================================================
echo.
echo 로컬 8000 포트 서버를 Cloudflare 보안 HTTPS 도메인으로 외부에 무료 연결합니다.
echo.

where cloudflared >nul 2>nul
if %errorlevel% neq 0 (
    echo [안내] cloudflared CLI가 감지되지 않았습니다.
    echo winget 또는 공식 다운로드를 통해 간편 설치할 수 있습니다:
    echo 명령어: winget install --id Cloudflare.cloudflared
    echo 또는 https://github.com/cloudflare/cloudflared/releases 에서 다운로드
    echo.
    pause
    exit /b
)

echo [연결 중...] Cloudflare Tunnel 시작...
cloudflared tunnel --url http://127.0.0.1:8000
pause
