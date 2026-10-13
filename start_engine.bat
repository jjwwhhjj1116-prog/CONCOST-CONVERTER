@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo ========================================================
echo   CONCOST 변환 엔진 (사내 PC) - Cloudflare Tunnel 연결
echo   직원 접속: https://concost-total-converter.pages.dev
echo   * 이 창이 켜져 있는 동안만 변환이 동작합니다.
echo ========================================================
python backend\engine_launcher.py
pause
