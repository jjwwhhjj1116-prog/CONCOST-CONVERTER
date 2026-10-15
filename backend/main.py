"""
변환 토탈웹 - 통합 백엔드 API 서버 (FastAPI)
- CAD 도면 변환(PDF <-> DXF <-> DWG): 사용자 전용 CONCOST-Converter-0.2.2 + LibreDWG/ZWCAD 정밀 엔진
- 비-CAD 전 포맷 변환(180+ 경로): KnifeLemon/Filee v1.10.2 아키텍처(FileeUniversalRouter) 완전 이식
- 동기 워커 스레드풀 + 세마포어 제어로 클라우드 컨테이너 이벤트 루프 블로킹 및 502 타임아웃 원천 차단
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
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
from backend.engines.filee_universal import FileeUniversalRouter
from backend.engines.general.image_engine import ImageConversionOptions, ImageEngine

app = FastAPI(
    title="CONCOST Total Converter API",
    description="CONCOST-Converter-0.2.2 CAD/DWG 정밀 엔진 & Filee v1.10.2 180+ 포맷 통합 변환 플랫폼",
    version="1.10.2",
)

# CORS 설정 (브라우저 직결 및 Cloudflare Pages 프록시 모두 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ENGINE_KEY: str = os.environ.get("ENGINE_KEY", "")
# 클라우드 컨테이너(512MB RAM) 동시 변환 시 OOM 방지를 위한 세마포어
CONVERSION_SEMAPHORE = threading.Semaphore(2)


@app.middleware("http")
async def engine_key_guard(request, call_next):
    """X-Engine-Key 또는 Bearer 토큰이 있는 인증 요청 및 헬스체크 허용"""
    from fastapi.responses import JSONResponse

    path = request.url.path
    if request.method == "OPTIONS" or path in ("/api/health", "/api/formats", "/api/catalog"):
        return await call_next(request)

    if ENGINE_KEY and path.startswith("/api/") and not path.startswith("/api/auth/"):
        req_key = request.headers.get("x-engine-key", "")
        auth_hdr = request.headers.get("authorization", "")
        token_q = request.query_params.get("t", "")
        # 프록시 X-Engine-Key 일치 또는 임직원 Bearer 토큰 보유 시 통과
        if req_key != ENGINE_KEY and not auth_hdr.startswith("Bearer ") and not token_q:
            return JSONResponse(status_code=403, content={"detail": "인증 토큰 또는 엔진 접근 키가 필요합니다."})
    return await call_next(request)


BASE_DIR: Path = Path(__file__).resolve().parent.parent
FRONTEND_DIR: Path = BASE_DIR / "frontend"
UPLOAD_DIR: Path = BASE_DIR / "storage" / "uploads"
OUTPUT_DIR: Path = BASE_DIR / "storage" / "outputs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

auth_mgr = AuthManager()


def _cleanup_old_storage(max_age_seconds: int = 3600) -> None:
    """오래된 업로드/출력 임시 디렉터리를 자동 정리하여 디스크 및 메모리를 보호한다."""
    now = time.time()
    for root_dir in (UPLOAD_DIR, OUTPUT_DIR):
        try:
            for item in root_dir.iterdir():
                if item.is_dir() and (now - item.stat().st_mtime) > max_age_seconds:
                    shutil.rmtree(item, ignore_errors=True)
        except Exception:
            pass


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
        },
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
        "targets": ["pdf", "docx", "hwpx", "txt", "xlsx", "html", "rtf", "odt", "epub"],
    },
    "spreadsheets": {
        "title": "표 / 내역서",
        "badge_count": 6,
        "extensions": [".xlsx", ".xls", ".csv", ".tsv", ".ods", ".pdf"],
        "targets": ["xlsx", "csv", "tsv", "ods", "pdf", "html", "docx", "hwpx"],
    },
    "images": {
        "title": "이미지",
        "badge_count": 12,
        "extensions": [".png", ".jpg", ".jpeg", ".webp", ".svg", ".bmp", ".tiff", ".tif", ".ico", ".gif", ".heic", ".psd"],
        "targets": ["webp", "png", "jpg", "ico", "bmp", "tiff", "gif", "pdf", "svg"],
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
        "targets": ["pdf", "epub", "azw3", "fb2", "cbz", "zip", "7z", "tar", "gz", "bz2"],
    },
    "mixed": {
        "title": "혼합 파일",
        "badge_count": 16,
        "extensions": ["*"],
        "targets": ["zip", "pdf", "png", "dxf", "xlsx", "mp4"],
    },
}


@app.get("/api/health")
def health_check() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "CONCOST-TotalConverter",
        "version": "1.10.2",
        "cad_engine": "CONCOST-Converter-0.2.2 + LibreDWG",
        "general_engine": "Filee-1.10.2-Universal",
    }


@app.get("/api/formats")
@app.get("/api/catalog")
def get_catalog() -> Dict[str, Any]:
    """Filee 레퍼런스 카탈로그 및 프로필 반환"""
    return FORMAT_CATALOG


@app.get("/api/cad/zwcad-status")
def get_cad_status() -> Dict[str, Any]:
    """ZWCAD 설치 및 LibreDWG 클라우드 DWG 가속 엔진 지원 상태 반환"""
    return CadEngine.get_zwcad_status()


@app.post("/api/convert", response_model=ConversionResponse)
def convert_file(
    file: UploadFile = File(...),
    target_format: str = Form(...),
    scale_multiplier: float = Form(1.0),
    auto_detect_scale: bool = Form(False),
    quality: int = Form(90),
    dpi: int = Form(300),
) -> ConversionResponse:
    """
    단일 파일 변환을 처리하는 다중 엔진 라우터 (동기 def로 선언하여 FastAPI 워커 스레드풀에서 비차단 실행)
    - CAD 관련 변환: 사용자 전용 CONCOST-Converter-0.2.2 + LibreDWG/ZWCAD
    - 비-CAD 변환: KnifeLemon/Filee 오픈소스 이식 엔진 (FileeUniversalRouter)
    """
    _cleanup_old_storage()
    task_id = str(uuid.uuid4())
    orig_name = Path(file.filename or "file").name
    ext = Path(orig_name).suffix.lower().lstrip(".")
    tgt = target_format.lower().strip().replace(" ", "_")

    task_upload_dir = UPLOAD_DIR / task_id
    task_output_dir = OUTPUT_DIR / task_id
    task_upload_dir.mkdir(parents=True, exist_ok=True)
    task_output_dir.mkdir(parents=True, exist_ok=True)

    input_file_path = task_upload_dir / orig_name
    with open(input_file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    out_ext = "mp4" if tgt == "mp4_720p" else tgt.split("_")[0]
    out_file_path = task_output_dir / f"{input_file_path.stem}.{out_ext}"
    meta: Dict[str, Any] = {}

    with CONVERSION_SEMAPHORE:
        try:
            # =====================================================================
            # 1. CAD 도면 변환 (사용자 전용 CONCOST-Converter-0.2.2 + LibreDWG/ZWCAD)
            # =====================================================================
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
                    "engine": f"CONCOST-Converter-0.2.2 ({cad_res.zwcad_engine or 'R2013 정밀 DXF'})",
                    "entities": cad_res.total_entities,
                    "lines": cad_res.lines_count,
                    "hatches": cad_res.hatches_count,
                    "applied_scale": cad_res.applied_scale,
                    "zwcad_engine": cad_res.zwcad_engine,
                    "warnings": cad_res.warnings,
                }

            elif ext == "dxf" and tgt == "dwg":
                cad_res = CadEngine.convert_dxf_to_dwg(input_file_path, out_file_path)
                if not cad_res.success:
                    raise HTTPException(status_code=500, detail=cad_res.error_message or "DXF -> DWG 변환 실패")
                meta = {
                    "engine": f"CONCOST DWG Engine ({cad_res.zwcad_engine})",
                    "entities": cad_res.total_entities,
                }

            elif ext == "dwg" and tgt == "dxf":
                cad_res = CadEngine.convert_dwg_to_dxf(input_file_path, out_file_path)
                if not cad_res.success:
                    raise HTTPException(status_code=500, detail=cad_res.error_message or "DWG -> DXF 변환 실패")
                meta = {"engine": "CONCOST LibreDWG (DWG -> DXF)"}

            elif ext in ("dxf", "dwg") and tgt in ("pdf", "svg", "png", "jpg", "jpeg", "webp"):
                with tempfile.TemporaryDirectory(prefix="cad_vis_") as tmp:
                    work_dxf = input_file_path
                    if ext == "dwg":
                        work_dxf = Path(tmp) / "stage.dxf"
                        d_res = CadEngine.convert_dwg_to_dxf(input_file_path, work_dxf)
                        if not d_res.success:
                            raise HTTPException(status_code=500, detail=d_res.error_message or "DWG 파싱 실패")
                    ok = CadEngine.render_dxf_to_visual(work_dxf, out_file_path, tgt, dpi=dpi)
                    if not ok:
                        raise HTTPException(status_code=500, detail=f"{ext.upper()} -> {tgt.upper()} 렌더링 실패")
                meta = {"engine": "CONCOST CAD Vector Renderer", "format": tgt.upper()}

            elif ext in ("dxf", "dwg") and tgt == ext:
                shutil.copy2(input_file_path, out_file_path)
                meta = {"engine": "CONCOST CAD Pass-through", "format": tgt.upper()}

            elif tgt in ("stl", "obj", "step", "iges", "dgn"):
                with tempfile.TemporaryDirectory(prefix="cad_3d_") as tmp:
                    work_dxf = Path(tmp) / "stage.dxf"
                    if ext == "dxf":
                        work_dxf = input_file_path
                    elif ext == "dwg":
                        d_res = CadEngine.convert_dwg_to_dxf(input_file_path, work_dxf)
                        if not d_res.success:
                            raise HTTPException(status_code=500, detail=d_res.error_message or "DWG 파싱 실패")
                    elif ext == "pdf":
                        c_res = CadEngine.convert_pdf_to_dxf(
                            input_file_path,
                            work_dxf,
                            CadConversionOptions(scale_multiplier=scale_multiplier, auto_detect_scale=auto_detect_scale),
                        )
                        if not c_res.success:
                            raise HTTPException(status_code=500, detail=c_res.error_message or "PDF->DXF 실패")
                    else:
                        CadEngine.import_3d_or_exchange_to_dxf(input_file_path, work_dxf)

                    ok = CadEngine.export_dxf_to_3d_or_exchange(work_dxf, out_file_path, tgt)
                    if not ok:
                        raise HTTPException(status_code=500, detail=f"3D/CAD 교환 포맷({tgt.upper()}) 생성 실패")
                meta = {"engine": f"CONCOST 3D/Exchange Engine ({tgt.upper()})", "format": tgt.upper()}

            elif ext in ("step", "stp", "iges", "igs", "stl", "obj", "dgn") and tgt in ("dxf", "dwg", "pdf", "svg", "png"):
                with tempfile.TemporaryDirectory(prefix="cad_imp_") as tmp:
                    stage_dxf = Path(tmp) / "imported.dxf"
                    CadEngine.import_3d_or_exchange_to_dxf(input_file_path, stage_dxf)
                    if tgt == "dxf":
                        shutil.copy2(stage_dxf, out_file_path)
                    elif tgt == "dwg":
                        r_dwg = CadEngine.convert_dxf_to_dwg(stage_dxf, out_file_path)
                        if not r_dwg.success:
                            raise HTTPException(status_code=500, detail=r_dwg.error_message or "DWG 변환 실패")
                    else:
                        CadEngine.render_dxf_to_visual(stage_dxf, out_file_path, tgt, dpi=dpi)
                meta = {"engine": "CONCOST 3D/Exchange Importer", "route": f"{ext.upper()} -> {tgt.upper()}"}

            elif ext in ("png", "jpg", "jpeg", "webp", "bmp", "tiff") and tgt in ("dxf", "dwg"):
                with tempfile.TemporaryDirectory(prefix="img_cad_") as tmp:
                    stage_pdf = Path(tmp) / "raster_stage.pdf"
                    ImageEngine.convert_image(
                        input_file_path, stage_pdf, ImageConversionOptions(target_format="PDF", dpi=dpi)
                    )
                    cad_opts = CadConversionOptions(scale_multiplier=scale_multiplier, raster_trace=True, target_format=tgt)
                    if tgt == "dwg":
                        c_res = CadEngine.convert_pdf_to_dwg(stage_pdf, out_file_path, cad_opts)
                    else:
                        c_res = CadEngine.convert_pdf_to_dxf(stage_pdf, out_file_path, cad_opts)
                    if not c_res.success:
                        raise HTTPException(status_code=500, detail=c_res.error_message or "이미지->CAD 추적 실패")
                meta = {"engine": "CONCOST Raster-to-CAD Tracer", "entities": c_res.total_entities}

            # =====================================================================
            # 2. PDF -> 고해상도 이미지/SVG 렌더링
            # =====================================================================
            elif ext == "pdf" and tgt in ("png", "jpg", "jpeg", "webp", "bmp", "tiff", "ico", "svg"):
                img_opts = ImageConversionOptions(target_format=tgt, dpi=dpi, quality=quality)
                rendered = ImageEngine.convert_pdf_to_images(input_file_path, task_output_dir, img_opts, page_index=0)
                if not rendered or not rendered[0].exists():
                    raise HTTPException(status_code=500, detail="PDF 이미지/SVG 렌더링 실패")
                out_file_path = rendered[0]
                meta = {"engine": "PyMuPDF Vector/High-Res Rasterizer", "dpi": dpi, "format": tgt.upper()}

            # =====================================================================
            # 3. KnifeLemon/Filee 유니버설 엔진 & 다단계 라우터 (비-CAD 전 포맷)
            # =====================================================================
            else:
                ok, final_path, u_meta = FileeUniversalRouter.convert(
                    input_path=input_file_path,
                    output_path=out_file_path,
                    source_ext=ext,
                    target_fmt=tgt,
                    dpi=dpi,
                    quality=quality,
                )
                if not ok or not final_path.exists():
                    raise HTTPException(
                        status_code=422,
                        detail=f"지원하지 않거나 변환할 수 없는 경로입니다: {ext.upper()} -> {tgt.upper()}",
                    )
                out_file_path = final_path
                meta = u_meta

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


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
