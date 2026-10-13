@echo off
chcp 65001 > nul
echo ========================================================
echo   CONCOST Total Studio - 변환 토탈웹 서버 구동기
echo ========================================================
echo.
echo [1/2] 필수 의존성 패키지 확인 중...
pip install -r requirements.txt --quiet

echo.
echo [2/2] FastAPI & Uvicorn 엔진 가동 중... (포트: 8000)
echo 브라우저 접속 주소: http://127.0.0.1:8000
echo.
echo * 창을 닫으면 서버가 종료됩니다.
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
pause
