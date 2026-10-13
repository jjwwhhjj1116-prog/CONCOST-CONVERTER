"""
표 및 문서 추출 엔진 (Table & Document Engine)
도면/내역서/일람표 PDF에서 격자 선분을 복원하고 텍스트를 셀 단위로 정확하게 매핑하여 Excel로 변환합니다.
(CONCOST 검증 알고리즘 기반)
"""
from dataclasses import dataclass, field
import math
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

import fitz  # PyMuPDF
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from shapely.geometry import LineString, box
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree


@dataclass
class TableCell:
    """복원된 개별 표 셀"""
    row: int
    col: int
    text: str
    bbox: Tuple[float, float, float, float]


@dataclass
class RecoveredTable:
    """복원된 표 구조"""
    table_index: int
    rows_count: int
    cols_count: int
    grid: List[List[str]]  # [행][열] 텍스트 매트릭스


class TableEngine:
    """PDF 표 복원 및 Excel 변환 엔진"""

    @staticmethod
    def extract_lines_and_texts(
        pdf_path: Path, page_index: int = 0
    ) -> Tuple[List[Tuple[Tuple[float, float], Tuple[float, float]]], List[Dict[str, Any]]]:
        """PDF 페이지에서 선분 좌표 쌍과 텍스트 바운딩 박스를 추출합니다."""
        lines: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        texts: List[Dict[str, Any]] = []

        with fitz.open(pdf_path) as doc:
            if page_index >= len(doc):
                return [], []
            page = doc[page_index]

            # 1. 드로잉에서 선분 추출
            for draw in page.get_drawings():
                for item in draw.get("items", []):
                    if item[0] == "l":  # line
                        p1, p2 = item[1], item[2]
                        lines.append(((p1.x, p1.y), (p2.x, p2.y)))
                    elif item[0] == "re":  # rect
                        r = item[1]
                        lines.append(((r.x0, r.y0), (r.x1, r.y0)))
                        lines.append(((r.x1, r.y0), (r.x1, r.y1)))
                        lines.append(((r.x1, r.y1), (r.x0, r.y1)))
                        lines.append(((r.x0, r.y1), (r.x0, r.y0)))

            # 2. 텍스트 추출 (words)
            for word in page.get_text("words"):
                x0, y0, x1, y1, text = word[:5]
                texts.append({
                    "text": text,
                    "bbox": (x0, y0, x1, y1),
                    "anchor": ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
                })

        return lines, texts

    @classmethod
    def recover_tables(
        cls,
        lines: List[Tuple[Tuple[float, float], Tuple[float, float]]],
        texts: List[Dict[str, Any]],
        tolerance: Optional[float] = None,
    ) -> List[RecoveredTable]:
        """선분 격자를 클러스터링하고 닫힌 사각형 셀을 복원하여 텍스트를 배치합니다."""
        if not lines or not texts:
            return []

        heights = [abs(t["bbox"][3] - t["bbox"][1]) for t in texts if t["bbox"][3] > t["bbox"][1]]
        tol = tolerance or (median(heights) * 0.15 if heights else 1.0)

        # 수평/수직 선분 분리
        segments = []
        xs, ys = [], []
        for a, b in lines:
            x0, y0 = map(float, a[:2])
            x1, y1 = map(float, b[:2])
            if abs(y1 - y0) <= tol and abs(x1 - x0) > tol:
                y = (y0 + y1) / 2.0
                segments.append(("h", min(x0, x1), max(x0, x1), y))
                xs.extend((x0, x1))
                ys.append(y)
            elif abs(x1 - x0) <= tol and abs(y1 - y0) > tol:
                x = (x0 + x1) / 2.0
                segments.append(("v", min(y0, y1), max(y0, y1), x))
                ys.extend((y0, y1))
                xs.append(x)

        if not segments:
            return []

        # 클러스터링 함수
        def cluster(values: List[float]) -> Dict[float, float]:
            res: Dict[float, float] = {}
            grp: List[float] = []
            for v in sorted(set(values)):
                if grp and v - grp[0] > tol:
                    c = sum(grp) / len(grp)
                    res.update((x, c) for x in grp)
                    grp = []
                grp.append(v)
            if grp:
                c = sum(grp) / len(grp)
                res.update((x, c) for x in grp)
            return res

        xm, ym = cluster(xs), cluster(ys)
        edges = []
        for axis, lo, hi, k in segments:
            coords = [(xm[lo], ym[k]), (xm[hi], ym[k])] if axis == "h" else [(xm[k], ym[lo]), (xm[k], ym[hi])]
            if coords[0] != coords[1]:
                edges.append(LineString(coords))

        if not edges:
            return []

        # 사각형 셀 다각형화
        cells = []
        for poly in polygonize(unary_union(edges)):
            r = box(*poly.bounds)
            if not poly.interiors and poly.area > tol * tol:
                cells.append(r)

        if not cells:
            return []

        # R-Tree 공간 인덱싱으로 텍스트를 셀에 할당
        tree = STRtree(cells)
        assigned: Dict[int, List[Dict[str, Any]]] = {i: [] for i in range(len(cells))}

        for t in texts:
            b = t.get("bbox")
            if not b:
                continue
            region = box(*b)
            hits = tree.query(region, predicate="intersects")
            if len(hits) > 0:
                best_cell = int(hits[0])
                assigned[best_cell].append(t)

        # 셀 좌표 정렬 및 격자 매트릭스 구성 (Y축 상->하, X축 좌->우)
        sorted_cells = sorted(
            range(len(cells)),
            key=lambda i: (round(cells[i].bounds[1], 1), round(cells[i].bounds[0], 1))
        )

        row_map: Dict[float, List[int]] = {}
        for i in sorted_cells:
            cy = round(cells[i].bounds[1] / 10.0) * 10  # 대략적인 행 클러스터링
            row_map.setdefault(cy, []).append(i)

        grid: List[List[str]] = []
        for cy in sorted(row_map.keys()):
            row_cells = sorted(row_map[cy], key=lambda i: cells[i].bounds[0])
            row_texts = []
            for c_idx in row_cells:
                cell_words = [item["text"] for item in assigned[c_idx]]
                row_texts.append(" ".join(cell_words).strip())
            grid.append(row_texts)

        return [RecoveredTable(
            table_index=0,
            rows_count=len(grid),
            cols_count=max((len(r) for r in grid), default=0),
            grid=grid
        )]

    @classmethod
    def convert_pdf_to_excel(cls, pdf_path: Path, excel_path: Path, page_index: int = 0) -> bool:
        """PDF 표를 복원하여 전문 Excel 서식 파일로 변환 저장합니다."""
        lines, texts = cls.extract_lines_and_texts(pdf_path, page_index)
        tables = cls.recover_tables(lines, texts)

        excel_path.parent.mkdir(parents=True, exist_ok=True)
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "표 복원 결과"

        # 스타일 정의
        thin_side = Side(border_style="thin", color="A0A0A0")
        cell_border = Border(top=thin_side, left=thin_side, right=thin_side, bottom=thin_side)
        header_fill = PatternFill(start_color="F2F4F8", end_color="F2F4F8", fill_type="solid")
        header_font = Font(name="맑은 고딕", size=10, bold=True)
        body_font = Font(name="맑은 고딕", size=9)

        if not tables or not tables[0].grid:
            # 표가 없을 경우 일반 텍스트 목록으로 기록
            ws.cell(row=1, column=1, value="[안내] 닫힌 표 경계선을 발견하지 못하여 텍스트 순서대로 기록합니다.")
            for r_idx, t in enumerate(texts, start=2):
                ws.cell(row=r_idx, column=1, value=t["text"])
        else:
            table = tables[0]
            for r_idx, row in enumerate(table.grid, start=1):
                for c_idx, val in enumerate(row, start=1):
                    cell = ws.cell(row=r_idx, column=c_idx, value=val)
                    cell.border = cell_border
                    cell.alignment = Alignment(vertical="center", wrap_text=True)
                    if r_idx == 1:
                        cell.fill = header_fill
                        cell.font = header_font
                    else:
                        cell.font = body_font

        # 열 너비 자동 조정
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            col_letter = openpyxl.utils.get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(12, min(max_len * 1.5, 40))

        wb.save(str(excel_path))
        wb.close()
        return True
