"""
[검수 루프 1] CAD/도면 엔진 검증 스크립트
테스트용 벡터 PDF(선, 사각형, 텍스트, 치수선)를 동적으로 생성한 후,
CadEngine으로 DXF 변환을 수행하고 FeedbackAgent를 통해 품질 및 정합성을 자동 검수합니다.
"""
from pathlib import Path
import sys

# 프로젝트 루트 경로 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fitz  # PyMuPDF
from backend.engines.cad.cad_engine import CadConversionOptions, CadEngine
from backend.verifier.feedback_agent import FeedbackAgent


def create_sample_cad_pdf(pdf_path: Path) -> None:
    """테스트용 건축/도면 샘플 PDF 생성"""
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)  # A4 가로 (pt 단위)

    # 1. 외곽선 및 벽체 선분
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(50, 50, 792, 545))  # 도면 프레임
    shape.draw_line(fitz.Point(100, 150), fitz.Point(700, 150))  # 벽체 중심선
    shape.draw_line(fitz.Point(100, 450), fitz.Point(700, 450))
    shape.draw_line(fitz.Point(100, 150), fitz.Point(100, 450))
    shape.draw_line(fitz.Point(700, 150), fitz.Point(700, 450))
    shape.finish(color=(0, 0, 0), width=1.5)
    shape.commit()

    # 2. 치수선 및 텍스트
    page.insert_text(fitz.Point(380, 140), "6000", fontsize=11)  # 6,000mm 치수
    page.insert_text(fitz.Point(80, 300), "3000", fontsize=11)   # 3,000mm 치수
    page.insert_text(fitz.Point(350, 560), "1F FLOOR PLAN (SCALE 1:100)", fontsize=14)

    doc.save(str(pdf_path))
    doc.close()


def run_cad_verification() -> bool:
    """CAD 엔진 단계별 검수 실행"""
    work_dir = Path("e:/■ 개발_TF팀/변환 토탈웹/temp_verify")
    work_dir.mkdir(parents=True, exist_ok=True)

    sample_pdf = work_dir / "sample_drawing.pdf"
    output_dxf = work_dir / "sample_drawing.dxf"

    # 1. 샘플 PDF 생성
    create_sample_cad_pdf(sample_pdf)

    # 2. CAD 변환 엔진 구동
    options = CadConversionOptions(
        scale_multiplier=1.0,
        auto_detect_scale=True,
        include_text=True
    )
    result = CadEngine.convert_pdf_to_dxf(sample_pdf, output_dxf, options)

    # 3. 피드백 에이전트를 통한 무결성/정합성 검수
    agent = FeedbackAgent(output_dir=work_dir)
    verification = agent.verify_cad_dxf(
        output_file=output_dxf,
        expected_min_entities=5,
        check_scale_factor=result.applied_scale
    )

    agent.print_report()
    return verification.passed


if __name__ == "__main__":
    success = run_cad_verification()
    sys.exit(0 if success else 1)
