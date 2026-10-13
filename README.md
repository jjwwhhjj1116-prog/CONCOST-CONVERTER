# CONCOST Total Studio (변환 토탈웹)

> **Filee 1.10.2 아키텍처 기반 다중 포맷 변환 엔진 + CONCOST-Converter CAD 정밀 엔진 + 사내 임직원 전용 인증 시스템**

---

## 🌟 주요 특징

1. **3단계 직관적 워크프로세스 (UX/UI)**:
   - **STEP 1 [BEFORE 원본 파일]**: 드래그 앤 드롭을 통한 파일 투입 및 확장자 자동 매칭
   - **STEP 2 [TRANSFORM 도넛 변환 휠 & 포맷 선택]**: 원형 궤도 휠 및 180+ 지원 포맷 카탈로그 검색
   - **STEP 3 [AFTER 목표 확인 & 즉시 변환]**: 실시간 진행률 카드 및 다운로드 제공

2. **CONCOST-Converter-0.2.2 CAD & DWG 정밀 엔진**:
   - **PDF ➔ DXF**: `PyMuPDF` + `fontTools` + `shapely` + `ezdxf` 기반 **3차 베지어 곡선 적응형 분할** 및 건축 레이어별(`PDF_LINES`, `PDF_FILLS`, `TEXT_OUTLINE`, `PDF_IMAGES`) 완벽 분리
   - **PDF ➔ DWG**: 로컬에 설치된 **ZWCAD COM API 연동**을 통해 순수 바이너리 DWG(`AC1032`) 생성 및 재열기 객체 수 일치 무결성 검증 통과
   - **축척 자동 감지**: `scale_detection.py`를 통한 도면 표제란(1:100 등) 및 치수선 분석

3. **6대 전 카테고리 실질 변환 엔진**:
   - **표 / 내역서**: PDF ➔ Excel (XLSX) 표 구조 및 격자선 복원
   - **고해상도 이미지**: PNG, JPG, WebP, ICO, BMP 상호 변환 및 PDF ➔ 300DPI 렌더링
   - **문서 / 텍스트**: PDF ➔ TXT 추출 및 TXT ➔ PDF 재합성
   - **아카이브**: 다중 파일 One ZIP 무손실 패킹

4. **사내 임직원 전용 로그인 시스템 (`concost-tech-scheduler` 스타일)**:
   - `CONNECT_TALK_직원계정.xlsx` (22개 시트, 117명 임직원) 자동 파싱 및 SHA-256 단방향 암호화
   - 초기 비밀번호 `1234` 통일 및 개인설정 비밀번호 변경 영속 저장 지원
   - 스플릿 딥네이비 보안 브리핑 모달 & 빠른 계정 선택 칩 탑재

---

## 🚀 빠른 시작 (로컬 실행)

### 1. 가상환경 및 패키지 설치
```bash
pip install -r requirements.txt
```

### 2. 서버 실행
```bash
# 원클릭 실행 (Windows)
start_server.bat

# 또는 직접 명령어 실행
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```
브라우저 접속: `http://127.0.0.1:8000`

---

## 🌐 Cloudflare 외부 배포 및 접속

사내 PC에서 구동 중인 CAD/DWG 무거운 엔진을 외부에서도 보안 HTTPS로 무료 접속할 수 있도록 Cloudflare Tunnel을 지원합니다.

```bash
# Cloudflare Quick Tunnel 원클릭 실행
start_cloudflare_tunnel.bat
```
실행 즉시 콘솔에 생성되는 임시 도메인(`https://xxxx.trycloudflare.com`) 또는 연결된 회사 도메인으로 사외 어디서나 접속 가능합니다.

---

## 🧪 피드백 에이전트 전수 검증
전 카테고리 엔진 및 인증 시스템의 무결성을 1초 만에 검수합니다:
```bash
python backend/tests/verify_all_categories.py
```
검수 결과: `[ALL PASS] (6/6)`

---

## 📁 디렉터리 구조
```text
├── backend/
│   ├── auth.py              # 117명 사내 임직원 계정 파싱 및 SHA-256 인증
│   ├── main.py              # FastAPI 통합 REST API 엔드포인트
│   ├── engines/
│   │   ├── cad/             # CONCOST-Converter 정밀 DXF/DWG 엔진 & ZWCAD COM 연동
│   │   ├── document/        # 표/내역서 복원 및 텍스트 엔진
│   │   ├── general/         # Pillow 기반 이미지 변환 엔진
│   │   └── archive/         # 무손실 ZIP 패킹 엔진
│   ├── verifier/            # 자동 무결성 검수 피드백 에이전트
│   └── tests/               # 6대 카테고리 전수 검증 스크립트
├── frontend/
│   ├── index.html           # 3단계 파이프라인 & 스플릿 모달 UI
│   ├── style.css            # Filee + 네이비 글래스모피즘 테마 스타일
│   └── app.js               # 워크프로세스 상태 머신 & 비동기 변환 컨트롤러
├── storage/                 # 변환 입출력 및 영속 유저 DB
├── requirements.txt         # 파이썬 의존성 패키지
├── start_server.bat         # 원클릭 서버 실행기
└── start_cloudflare_tunnel.bat # Cloudflare 터널 실행기
```
