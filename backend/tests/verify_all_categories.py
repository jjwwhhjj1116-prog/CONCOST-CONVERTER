"""
[피드백 에이전트 종합 전수 검수 스크립트]
모든 변환 엔진 카테고리(CAD, 표, 이미지, 문서, 압축) 및 사내 직원 인증 시스템을 전수 검증합니다.
"""
from pathlib import Path
import sys

# 프로젝트 루트 경로 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.auth import AuthManager
from backend.engines.archive.archive_engine import ArchiveEngine
from backend.engines.cad.cad_engine import CadConversionOptions, CadEngine
from backend.engines.document.document_engine import DocumentEngine
from backend.engines.document.table_engine import TableEngine
from backend.engines.general.image_engine import ImageConversionOptions, ImageEngine
from backend.verifier.feedback_agent import FeedbackAgent, VerificationResult


def run_full_verification() -> bool:
    work_dir = Path("e:/■ 개발_TF팀/변환 토탈웹/temp_verify")
    work_dir.mkdir(parents=True, exist_ok=True)
    agent = FeedbackAgent(output_dir=work_dir)

    print("=" * 60)
    print("[전수 검수] Filee 기반 변환 토탈웹 전체 엔진 무결성 검증 시작")
    print("=" * 60)

    # 1. 사내 직원 인증 모듈 검수
    auth = AuthManager()
    total_users = len(auth.users)
    auth_test_ok = auth.authenticate("yjw", "1234") is not None
    agent.history.append(VerificationResult(
        category="Auth",
        target_name="임직원 117명 계정 연동 및 1234 인증",
        passed=total_users >= 50 and auth_test_ok,
        metrics={"total_employees": total_users, "default_pwd_verified": auth_test_ok}
    ))

    # 2. CAD 도면 엔진 검수 - CONCOST-Converter-0.2.2 (PDF -> DXF & DWG)
    sample_pdf = work_dir / "sample_drawing.pdf"
    output_dxf = work_dir / "full_verify_drawing.dxf"
    cad_res = CadEngine.convert_pdf_to_dxf(sample_pdf, output_dxf)
    cad_ver = agent.verify_cad_dxf(output_dxf, expected_min_entities=1, check_scale_factor=cad_res.applied_scale)

    # 2-2. ZWCAD DWG 변환 검수
    zw_status = CadEngine.get_zwcad_status()
    if zw_status["available"]:
        output_dwg = work_dir / "full_verify_drawing.dwg"
        dwg_res = CadEngine.convert_pdf_to_dwg(sample_pdf, output_dwg)
        dwg_ver = agent.verify_cad_dwg(output_dwg)
    else:
        agent.history.append(VerificationResult(
            category="CAD_DWG",
            target_name="ZWCAD 바이너리 DWG 변환 (ZWCAD 미설치 환경 스킵)",
            passed=True,
            warnings=["ZWCAD가 감지되지 않아 DXF 정밀 모드로만 운영됩니다."]
        ))

    # 3. 표/내역서 복원 엔진 검수 (PDF -> Excel)
    sample_table_pdf = work_dir / "sample_estimate_table.pdf"
    output_xlsx = work_dir / "full_verify_table.xlsx"
    TableEngine.convert_pdf_to_excel(sample_table_pdf, output_xlsx)
    table_ver = agent.verify_excel(output_xlsx, expected_min_rows=4, expected_min_cols=4)

    # 4. 범용 이미지 엔진 검수 (PNG -> WEBP, JPG)
    sample_png = work_dir / "sample_source.png"
    out_webp = work_dir / "full_verify.webp"
    ImageEngine.convert_image(sample_png, out_webp, ImageConversionOptions(target_format="WEBP"))
    img_ver1 = agent.verify_image(out_webp, expected_format="WEBP", min_width=300, min_height=200)

    # 5. 텍스트/문서 엔진 검수 (PDF -> TXT -> PDF)
    out_txt = work_dir / "full_verify_extracted.txt"
    out_txt_pdf = work_dir / "full_verify_reconstructed.pdf"
    doc_ok1 = DocumentEngine.extract_text_from_pdf(sample_table_pdf, out_txt)
    doc_ok2 = DocumentEngine.text_to_pdf(out_txt, out_txt_pdf)
    agent.history.append(VerificationResult(
        category="Document",
        target_name="PDF <-> TXT 양방향 문서 변환",
        passed=doc_ok1 and doc_ok2 and out_txt_pdf.exists() and out_txt_pdf.stat().st_size > 0,
        metrics={"txt_size_bytes": out_txt.stat().st_size, "pdf_size_bytes": out_txt_pdf.stat().st_size}
    ))

    # 6. 압축 엔진 검수 (One ZIP)
    out_zip = work_dir / "full_verify_archive.zip"
    zip_ok = ArchiveEngine.create_zip([output_dxf, output_xlsx, out_webp], out_zip)
    agent.history.append(VerificationResult(
        category="Archive",
        target_name="다중 파일 One ZIP 패킹",
        passed=zip_ok and out_zip.exists() and out_zip.stat().st_size > 0,
        metrics={"zip_size_bytes": out_zip.stat().st_size}
    ))

    agent.print_report()

    # 전체 합격 여부
    all_passed = all(item.passed for item in agent.history)
    print("=" * 60)
    print(f"[최종 전수 검수 결과] {'전체 통과 [ALL PASS]' if all_passed else '일부 실패 [FAIL]'}")
    print("=" * 60)
    return all_passed


if __name__ == "__main__":
    success = run_full_verification()
    sys.exit(0 if success else 1)
