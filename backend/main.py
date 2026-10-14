"""
변환 토탈웹 - 통합 백엔드 API 서버 (FastAPI)
Filee 180+ 포맷 라우팅 아키텍처 및 CONCOST 특화 엔진 결합
"""
from dataclasses import asdict
from enum import Enum
import io
import os
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional
import uuid
import zipfile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.auth import AuthManager
from backend.engines.cad.cad_engine import CadConversionOptions, CadEngine
from backend.engines.document.document_engine import DocumentEngine
from backend.engines.document.table_engine import TableEngine
from backend.engines.general.image_engine import ImageConversionOptions, ImageEngine

app = FastAPI(
    title="CONCOST Total Converter API",
    description="Filee v1.10.2 아키텍처 기반 사내·서비스용 도면·문서·미디어 통합 변환 플랫폼",
    version="1.10.2",
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 터널 주소는 공개 URL이므로, ENGINE_KEY가 설정되면 변환/다운로드 API에 키를 요구
ENGINE_KEY: str = os.environ.get("ENGINE_KEY", "")


@app.middleware("http")
async def engine_key_guard(request, call_next):
    """Cloudflare 프록시가 붙여주는 X-Engine-Key 검사 (로컬 직접 접속은 키 미설정 시 허용)"""
    from fastapi.responses import JSONResponse

    path = request.url.path
    via_tunnel = "cf-connecting-ip" in request.headers  # Cloudflare 엣지가 항상 덮어쓰는 헤더
    if ENGINE_KEY and via_tunnel and path.startswith("/api/") and path != "/api/health":
        if request.headers.get("x-engine-key") != ENGINE_KEY:
            return JSONResponse(status_code=403, content={"detail": "엔진 접근 키가 올바르지 않습니다."})
    return await call_next(request)

BASE_DIR: Path = Path(__file__).resolve().parent.parent
FRONTEND_DIR: Path = BASE_DIR / "frontend"
UPLOAD_DIR: Path = BASE_DIR / "storage" / "uploads"
OUTPUT_DIR: Path = BASE_DIR / "storage" / "outputs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

auth_mgr = AuthManager()


class LoginRequest(BaseModel):
    login_id: str
    password: str


class ChangePasswordRequest(BaseModel):
    login_id: str
    old_password: str
    new_password: str


@app.get("/api/auth/employees")
def get_employees() -> Dict[str, Any]:
    """로그인 드롭다운용 사내 임직원 명단 반환"""
    return {"employees": auth_mgr.get_employee_public_list()}


@app.post("/api/auth/login")
def login(req: LoginRequest) -> Dict[str, Any]:
    """사내 임직원 로그인 (초기 비밀번호: 1234)"""
    user = auth_mgr.authenticate(req.login_id, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호(초기: 1234)가 올바르지 않습니다.")
    return {
        "success": True,
        "token": f"token-{user.login_id}-{uuid.uuid4().hex[:12]}",
        "user": {
            "login_id": user.login_id,
            "name": user.name,
            "department": user.department,
            "rank": user.rank,
            "email": user.email,
            "role": user.role,
        }
    }


@app.post("/api/auth/change-password")
def change_password(req: ChangePasswordRequest) -> Dict[str, Any]:
    """개인설정 비밀번호 변경"""
    ok = auth_mgr.change_password(req.login_id, req.old_password, req.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail="기존 비밀번호가 일치하지 않습니다.")
    return {"success": True, "message": "비밀번호가 성공적으로 변경되었습니다."}


class ConversionResponse(BaseModel):
    task_id: str
    original_name: str
    target_format: str
    success: bool
    download_url: Optional[str] = None
    file_size_bytes: int = 0
    message: str = "변환 완료"
    metadata: Dict[str, Any] = {}


# Filee 레퍼런스 180+ 포맷 매핑 카탈로그
FORMAT_CATALOG: Dict[str, Dict[str, Any]] = {
    "cad": {
        "title": "CAD 도면",
        "badge_count": 5,
        "extensions": [".dwg", ".dxf", ".pdf", ".dgn", ".step"],
        "targets": ["dxf", "dwg", "pdf", "png", "svg"],
    },
    "documents": {
        "title": "문서 / 한글",
        "badge_count": 8,
        "extensions": [".hwp", ".hwpx", ".docx", ".doc", ".pdf", ".odt", ".rtf", ".txt"],
        "targets": ["pdf", "docx", "hwpx", "txt", "xlsx"],
    },
    "spreadsheets": {
        "title": "표 / 내역서",
        "badge_count": 6,
        "extensions": [".xlsx", ".xls", ".csv", ".tsv", ".ods", ".pdf"],
        "targets": ["xlsx", "csv", "pdf", "html"],
    },
    "images": {
        "title": "이미지",
        "badge_count": 12,
        "extensions": [".png", ".jpg", ".jpeg", ".webp", ".svg", ".bmp", ".tiff", ".tif", ".ico", ".gif", ".heic", ".psd"],
        "targets": ["webp", "png", "jpg", "ico", "bmp", "tiff", "pdf", "svg"],
    },
    "media_video": {
        "title": "동영상",
        "badge_count": 8,
        "extensions": [".mp4", ".webm", ".mov", ".mkv", ".avi", ".flv", ".wmv", ".gif"],
        "targets": ["mp4", "mp4 720p", "webm", "mov", "mkv", "gif", "mp3"],
    },
    "media_audio": {
        "title": "오디오",
        "badge_count": 6,
        "extensions": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a"],
        "targets": ["mp3", "wav", "flac", "aac", "ogg"],
    },
    "ebooks": {
        "title": "전자책 / 압축",
        "badge_count": 7,
        "extensions": [".epub", ".mobi", ".azw3", ".fb2", ".cbz", ".zip", ".tar.gz", ".7z"],
        "targets": ["pdf", "epub", "azw3", "zip", "cbz"],
    },
    "mixed": {
        "title": "혼합 파일",
        "badge_count": 16,
        "extensions": ["*"],
        "targets": ["zip", "pdf", "png", "dxf", "xlsx", "mp4"],
    },
}


@app.get("/api/health")
def health_check() -> Dict[str, str]:
    return {"status": "ok", "service": "CONCOST-TotalConverter", "version": "1.10.2"}


@app.get("/api/formats")
@app.get("/api/catalog")
def get_catalog() -> Dict[str, Any]:
    """Filee 레퍼런스 카탈로그 및 프로필 반환"""
    return FORMAT_CATALOG


@app.get("/api/cad/zwcad-status")
def get_cad_status() -> Dict[str, Any]:
    """ZWCAD 설치 및 DWG 가속 엔진 지원 상태 반환"""
    return CadEngine.get_zwcad_status()


@app.post("/api/convert", response_model=ConversionResponse)
async def convert_file(
    file: UploadFile = File(...),
    target_format: str = Form(...),
    scale_multiplier: float = Form(1.0),
    auto_detect_scale: bool = Form(False),
    quality: int = Form(90),
    dpi: int = Form(300),
) -> ConversionResponse:
    """단일 파일 변환을 처리하는 다중 엔진 라우터"""
    task_id = str(uuid.uuid4())
    orig_name = file.filename or "file"
    ext = Path(orig_name).suffix.lower().lstrip(".")
    tgt = target_format.lower().strip().replace(" ", "_")

    task_upload_dir = UPLOAD_DIR / task_id
    task_output_dir = OUTPUT_DIR / task_id
    task_upload_dir.mkdir(parents=True, exist_ok=True)
    task_output_dir.mkdir(parents=True, exist_ok=True)

    input_file_path = task_upload_dir / orig_name
    with open(input_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    out_file_path = task_output_dir / f"{input_file_path.stem}.{tgt.split('_')[0]}"
    meta: Dict[str, Any] = {}

    try:
        # 1. CAD 도면 변환 (PDF -> DXF / DWG) - CONCOST-Converter-0.2.2 알고리즘
        if ext == "pdf" and tgt in ("dxf", "dwg"):
            cad_opts = CadConversionOptions(
                scale_multiplier=scale_multiplier,
                auto_detect_scale=auto_detect_scale,
                page_number=1,
                target_format=tgt,
            )
            if tgt == "dwg":
                cad_res = CadEngine.convert_pdf_to_dwg(input_file_path, out_file_path, cad_opts)
            else:
                cad_res = CadEngine.convert_pdf_to_dxf(input_file_path, out_file_path, cad_opts)

            if not cad_res.success:
                raise HTTPException(status_code=500, detail=cad_res.error_message or "CAD 변환 실패")
            meta = {
                "engine": f"CONCOST-Converter-0.2.2 ({'ZWCAD Native DWG' if tgt == 'dwg' else 'R2013 정밀 DXF'})",
                "entities": cad_res.total_entities,
                "lines": cad_res.lines_count,
                "hatches": cad_res.hatches_count,
                "applied_scale": cad_res.applied_scale,
                "zwcad_engine": cad_res.zwcad_engine,
                "warnings": cad_res.warnings,
            }

        # 2. 표 / 내역서 복원 (PDF -> XLSX / CSV / HTML 및 XLSX <-> CSV)
        elif ext == "pdf" and tgt in ("xlsx", "csv", "html"):
            if tgt == "xlsx":
                ok = TableEngine.convert_pdf_to_excel(input_file_path, out_file_path)
            elif tgt == "csv":
                ok = TableEngine.convert_pdf_to_csv(input_file_path, out_file_path)
            else:
                ok = TableEngine.convert_pdf_to_html(input_file_path, out_file_path)
            if not ok:
                raise HTTPException(status_code=500, detail=f"표 복원 {tgt.upper()} 변환 실패")
            meta = {"engine": "CONCOST TableGridRestoration", "format": tgt.upper()}

        elif ext in ("xlsx", "xls") and tgt == "csv":
            ok = TableEngine.convert_excel_to_csv(input_file_path, out_file_path)
            if not ok:
                raise HTTPException(status_code=500, detail="Excel -> CSV 변환 실패")
            meta = {"engine": "CONCOST SpreadsheetEngine", "format": "CSV"}

        elif ext in ("csv", "tsv") and tgt == "xlsx":
            ok = TableEngine.convert_csv_to_excel(input_file_path, out_file_path)
            if not ok:
                raise HTTPException(status_code=500, detail="CSV -> Excel 변환 실패")
            meta = {"engine": "CONCOST SpreadsheetEngine", "format": "XLSX"}

        # 2-2. 문서 / 텍스트 양방향 변환 (PDF <-> TXT)
        elif ext == "pdf" and tgt == "txt":
            ok = DocumentEngine.extract_text_from_pdf(input_file_path, out_file_path)
            if not ok:
                raise HTTPException(status_code=500, detail="PDF 텍스트 추출 실패")
            meta = {"engine": "CONCOST DocumentEngine", "format": "TXT"}

        elif ext == "txt" and tgt == "pdf":
            ok = DocumentEngine.text_to_pdf(input_file_path, out_file_path)
            if not ok:
                raise HTTPException(status_code=500, detail="TXT -> PDF 문서 생성 실패")
            meta = {"engine": "CONCOST DocumentEngine (Korean Font)", "format": "PDF"}

        # 3. PDF -> 이미지/벡터 렌더링 (PNG, JPG, WEBP, BMP, TIFF, ICO, SVG)
        elif ext == "pdf" and tgt in ("png", "jpg", "jpeg", "webp", "bmp", "tiff", "ico", "svg"):
            img_opts = ImageConversionOptions(target_format=tgt, dpi=dpi, quality=quality)
            rendered = ImageEngine.convert_pdf_to_images(input_file_path, task_output_dir, img_opts, page_index=0)
            if not rendered or not rendered[0].exists():
                raise HTTPException(status_code=500, detail="PDF 이미지/SVG 렌더링 실패")
            out_file_path = rendered[0]
            meta = {"engine": "PyMuPDF Vector/High-Res Rasterizer", "dpi": dpi, "format": tgt.upper()}

        # 4. 이미지 상호 변환 및 이미지 -> PDF 변환 (PNG, JPG, WEBP, ICO, BMP, TIFF, PDF)
        elif ext in ("png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif", "ico", "gif") and tgt in (
            "png", "jpg", "jpeg", "webp", "bmp", "tiff", "ico", "pdf"
        ):
            img_opts = ImageConversionOptions(target_format=tgt, quality=quality)
            ok = ImageEngine.convert_image(input_file_path, out_file_path, img_opts)
            if not ok:
                raise HTTPException(status_code=500, detail="이미지 변환 실패")
            meta = {"engine": "Pillow Converter", "quality": quality, "format": tgt.upper()}

        # 5. 모든 파일을 단일 ZIP으로 압축 ("One ZIP")
        elif tgt == "zip":
            zip_out = task_output_dir / f"{input_file_path.stem}.zip"
            with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(input_file_path, arcname=input_file_path.name)
            out_file_path = zip_out
            meta = {"engine": "Deflate Zip Engine", "archived_files": 1}

        # 6. 미구현 경로: 원본 복사로 성공을 위장하지 않고 명시적으로 실패 처리
        else:
            raise HTTPException(
                status_code=422,
                detail=f"아직 지원하지 않는 변환 경로입니다: {ext.upper()} -> {tgt.upper()}",
            )

        file_size = out_file_path.stat().st_size if out_file_path.exists() else 0
        download_url = f"/api/download/{task_id}/{out_file_path.name}"

        return ConversionResponse(
            task_id=task_id,
            original_name=orig_name,
            target_format=tgt,
            success=True,
            download_url=download_url,
            file_size_bytes=file_size,
            message="성공적으로 변환되었습니다.",
            metadata=meta,
        )

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"변환 엔진 실행 오류: {str(e)}")


@app.get("/api/download/{task_id}/{filename}")
def download_result(task_id: str, filename: str) -> FileResponse:
    target = OUTPUT_DIR / task_id / filename
    if not target.exists():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    return FileResponse(path=str(target), filename=filename)


# 프론트엔드 마운트
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
