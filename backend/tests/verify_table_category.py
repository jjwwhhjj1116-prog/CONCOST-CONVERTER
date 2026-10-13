"""
[검수 루프 2] 문서 및 표/Excel 엔진 검증 스크립트
표 격자선과 데이터를 포함하는 샘플 PDF를 생성하고,
TableEngine으로 Excel 변환을 수행한 후 FeedbackAgent로 무결성을 자동 검수합니다.
"""
from pathlib import Path
import sys

# 프로젝트 루트 경로 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fitz  # PyMuPDF
from backend.engines.document.table_engine import TableEngine
from backend.verifier.feedback_agent import FeedbackAgent


def create_sample_table_pdf(pdf_path: Path) -> None:
    """테스트용 건축 적산 내역서 표 PDF 생성"""
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4 세로

    shape = page.new_shape()

    # 표 외곽 및 격자선 좌표
    x0, y0 = 50, 80
    col_widths = [60, 150, 70, 70, 70, 75]
    row_height = 25
    rows_count = 5

    # 가로선 그리기
    for r in range(rows_count + 1):
        y = y0 + r * row_height
        shape.draw_line(fitz.Point(x0, y), fitz.Point(x0 + sum(col_widths), y))

    # 세로선 그리기
    cur_x = x0
    for w in [0] + col_widths:
        cur_x += w
        shape.draw_line(fitz.Point(cur_x, y0), fitz.Point(cur_x, y0 + rows_count * row_height))

    shape.finish(color=(0, 0, 0), width=1.0)
    shape.commit()

    # 표 헤더 텍스트
    headers = ["순번", "품명 및 규격", "단위", "수량", "단가", "금액"]
    cur_x = x0
    for idx, text in enumerate(headers):
        page.insert_text(fitz.Point(cur_x + 10, y0 + 17), text, fontsize=9)
        cur_x += col_widths[idx]

    # 표 내용 데이터 (적산 내역 샘플)
    sample_data = [
        ["1", "레미콘 25-24-150", "m3", "120.5", "85,000", "10,242,500"],
        ["2", "이형철근 HD10", "ton", "4.2", "920,000", "3,864,000"],
        ["3", "이형철근 HD13", "ton", "8.5", "910,000", "7,735,000"],
        ["4", "거푸집 3회 합판", "m2", "340.0", "28,000", "9,520,000"],
    ]

    for r_idx, row in enumerate(sample_data, start=1):
        cur_x = x0
        y = y0 + r_idx * row_height + 17
        for c_idx, val in enumerate(row):
            page.insert_text(fitz.Point(cur_x + 8, y), val, fontsize=8)
            cur_x += col_widths[c_idx]

    doc.save(str(pdf_path))
    doc.close()


def run_table_verification() -> bool:
    """표/Excel 변환 엔진 검수 실행"""
    work_dir = Path("e:/■ 개발_TF팀/변환 토탈웹/temp_verify")
    work_dir.mkdir(parents=True, exist_ok=True)

    sample_pdf = work_dir / "sample_estimate_table.pdf"
    output_xlsx = work_dir / "sample_estimate_table.xlsx"

    # 1. 샘플 내역서 표 PDF 생성
    create_sample_table_pdf(sample_pdf)

    # 2. 표 복원 엔진 실행
    TableEngine.convert_pdf_to_excel(sample_pdf, output_xlsx)

    # 3. 피드백 에이전트를 통한 무결성/정합성 검수
    agent = FeedbackAgent(output_dir=work_dir)
    verification = agent.verify_excel(
        output_file=output_xlsx,
        expected_min_rows=4,
        expected_min_cols=4,
    )

    agent.print_report()
    return verification.passed


if __name__ == "__main__":
    success = run_table_verification()
    sys.exit(0 if success else 1)
