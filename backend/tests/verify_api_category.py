"""
[검수 루프 4] FastAPI REST API 통합 검증 스크립트
TestClient를 통해 /api/health, /api/formats, 그리고 CAD, 표(Excel), 이미지 변환 엔드포인트를 호출하고
피드백 에이전트를 통해 E2E 작동 정합성을 검수합니다.
"""
from io import BytesIO
from pathlib import Path
import sys

# 프로젝트 루트 경로 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient
from backend.main import app
from backend.verifier.feedback_agent import FeedbackAgent, VerificationResult

client = TestClient(app)


def run_api_verification() -> bool:
    """FastAPI 통합 API 검수 실행"""
    work_dir = Path("e:/■ 개발_TF팀/변환 토탈웹/temp_verify")
    agent = FeedbackAgent(output_dir=work_dir)

    # 1. 헬스체크 및 포맷 확인
    health_res = client.get("/api/health")
    formats_res = client.get("/api/formats")
    assert health_res.status_code == 200, "헬스체크 실패"
    assert formats_res.status_code == 200, "포맷 안내 실패"

    # 2. PDF -> DXF API 호출 테스트
    pdf_path = work_dir / "sample_drawing.pdf"
    with open(pdf_path, "rb") as f:
        cad_res = client.post(
            "/api/convert",
            files={"file": ("drawing.pdf", f, "application/pdf")},
            data={"target_format": "dxf", "scale_multiplier": "1.0", "auto_detect_scale": "true"}
        )

    cad_ok = cad_res.status_code == 200 and cad_res.json().get("success") is True
    agent.history.append(VerificationResult(
        category="API",
        target_name="POST /api/convert (PDF->DXF)",
        passed=cad_ok,
        metrics=cad_res.json().get("metadata", {})
    ))

    # 3. PDF -> XLSX API 호출 테스트
    table_pdf_path = work_dir / "sample_estimate_table.pdf"
    with open(table_pdf_path, "rb") as f:
        excel_res = client.post(
            "/api/convert",
            files={"file": ("estimate.pdf", f, "application/pdf")},
            data={"target_format": "xlsx"}
        )

    excel_ok = excel_res.status_code == 200 and excel_res.json().get("success") is True
    agent.history.append(VerificationResult(
        category="API",
        target_name="POST /api/convert (PDF->XLSX)",
        passed=excel_ok,
        metrics=excel_res.json().get("metadata", {})
    ))

    # 4. PNG -> WEBP API 호출 테스트
    png_path = work_dir / "sample_source.png"
    with open(png_path, "rb") as f:
        img_res = client.post(
            "/api/convert",
            files={"file": ("source.png", f, "image/png")},
            data={"target_format": "webp", "quality": "95"}
        )

    img_ok = img_res.status_code == 200 and img_res.json().get("success") is True
    agent.history.append(VerificationResult(
        category="API",
        target_name="POST /api/convert (PNG->WEBP)",
        passed=img_ok,
        metrics=img_res.json().get("metadata", {})
    ))

    agent.print_report()
    return cad_ok and excel_ok and img_ok


if __name__ == "__main__":
    success = run_api_verification()
    sys.exit(0 if success else 1)
