"""
문서 및 텍스트 변환 엔진 (Document & Text Engine)
TXT, Markdown, PDF, HTML 간 상호 텍스트 추출 및 문서 변환을 수행합니다.
"""
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF


class DocumentEngine:
    """문서 및 텍스트 변환기"""

    @classmethod
    def extract_text_from_pdf(cls, pdf_path: Path, output_txt: Path) -> bool:
        """PDF에서 텍스트 및 마크다운 구조 추출"""
        output_txt.parent.mkdir(parents=True, exist_ok=True)
        text_content = []
        with fitz.open(pdf_path) as doc:
            for page_idx, page in enumerate(doc):
                text_content.append(f"--- [Page {page_idx + 1}] ---")
                text_content.append(page.get_text())

        with open(output_txt, "w", encoding="utf-8") as f:
            f.write("\n".join(text_content))
        return True

    @classmethod
    def text_to_pdf(cls, txt_path: Path, output_pdf: Path) -> bool:
        """텍스트 파일을 기반으로 정형 PDF 문서 생성"""
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)  # A4

        with open(txt_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()

        y = 50
        for line in lines:
            line = line.rstrip()
            if y > 780:
                page = doc.new_page(width=595, height=842)
                y = 50
            page.insert_text(fitz.Point(50, y), line, fontsize=10)
            y += 18

        doc.save(str(output_pdf))
        doc.close()
        return True
