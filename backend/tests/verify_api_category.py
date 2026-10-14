"""
[검수 루프 4] FastAPI REST API 통합 검증 스크립트
TestClient를 통해 /api/health, /api/formats, 그리고 CAD(DXF/DWG), 표(XLSX/CSV/HTML),
문서(PDF<->TXT), 이미지(PNG->WEBP/PDF, PDF->PNG/SVG), 압축(ZIP) 엔드포인트를 전수 호출하고
피드백 에이전트를 통해 E2E 작동 정합성을 검수합니다.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
from backend.main import app
from backend.verifier.feedback_agent import FeedbackAgent, VerificationResult

client = TestClient(app)


def run_api_verification() -> bool:
    """FastAPI 통합 API 전수 검수 실행"""
    work_dir = Path("e:/■ 개발_TF팀/변환 토탈웹/temp_verify")
    agent = FeedbackAgent(output_dir=work_dir)

    health_res = client.get("/api/health")
    formats_res = client.get("/api/formats")
    assert health_res.status_code == 200, "헬스체크 실패"
    assert formats_res.status_code == 200, "포맷 안내 실패"

    pdf_path = work_dir / "sample_drawing.pdf"
    table_pdf_path = work_dir / "sample_estimate_table.pdf"
    png_path = work_dir / "sample_source.png"

    cases = [
        ("PDF->DXF", pdf_path, "application/pdf", {"target_format": "dxf", "scale_multiplier": "1.0", "auto_detect_scale": "true"}),
        ("PDF->XLSX", table_pdf_path, "application/pdf", {"target_format": "xlsx"}),
        ("PDF->CSV", table_pdf_path, "application/pdf", {"target_format": "csv"}),
        ("PDF->HTML", table_pdf_path, "application/pdf", {"target_format": "html"}),
        ("PDF->TXT", table_pdf_path, "application/pdf", {"target_format": "txt"}),
        ("PDF->SVG", pdf_path, "application/pdf", {"target_format": "svg"}),
        ("PDF->PNG", pdf_path, "application/pdf", {"target_format": "png", "dpi": "300"}),
        ("PNG->WEBP", png_path, "image/png", {"target_format": "webp", "quality": "95"}),
        ("PNG->PDF", png_path, "image/png", {"target_format": "pdf"}),
        ("PNG->ZIP", png_path, "image/png", {"target_format": "zip"}),
    ]

    all_ok = True
    for label, src, mime, form_data in cases:
        with open(src, "rb") as f:
            res = client.post("/api/convert", files={"file": (src.name, f, mime)}, data=form_data)
        body = res.json() if res.status_code == 200 else {}
        dl_url = body.get("download_url", "")
        dl_res = client.get(dl_url) if dl_url else None
        ok = res.status_code == 200 and body.get("success") is True and dl_res is not None and dl_res.status_code == 200 and len(dl_res.content) > 0
        if not ok:
            all_ok = False
        agent.history.append(VerificationResult(
            category="API",
            target_name=f"POST /api/convert ({label})",
            passed=ok,
            metrics={"size_bytes": len(dl_res.content) if dl_res else 0, **body.get("metadata", {})},
            errors=[] if ok else [f"HTTP {res.status_code}: {res.text[:200]}"],
        ))

    agent.print_report()
    return all_ok


if __name__ == "__main__":
    success = run_api_verification()
    sys.exit(0 if success else 1)
