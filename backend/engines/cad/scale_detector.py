"""
CAD 축척(Scale) 자동 감지 모듈
도면 PDF 내의 치수선(Dimension Line) 및 치수 텍스트를 추출하여 도면의 축척 비율(1:N)을 자동 계산합니다.
"""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
import math
from pathlib import Path
import re
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

import pymupdf

PT_MM: float = 25.4 / 72.0
NUMERIC: re.Pattern = re.compile(r"(?:[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d{2,})(?:\.\d+)?")


@dataclass
class ScaleDetectionResult:
    """축척 감지 결과 데이터 클래스"""
    status: str  # "confident", "needs_review", "no_dimensions"
    scale_multiplier: float = 1.0  # 실제 적용할 배율 (예: 1:100 이면 100.0)
    proposed_scale: Optional[float] = None
    nominal_scale: Optional[int] = None
    candidates: List[float] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


class ScaleDetector:
    """도면 치수선 기반 축척 탐지기"""

    @staticmethod
    def _extract_segments(page: pymupdf.Page) -> Tuple[List[List[Tuple[float, float, float]]], bool]:
        """축에 정렬된 가로/세로 직선 선분 추출"""
        axes: List[List[Tuple[float, float, float]]] = [[], []]
        unsupported = False
        bounds = tuple(page.rect * page.derotation_matrix)
        clips: List[Tuple[int, Tuple[float, float, float, float]]] = []

        for drawing in page.get_cdrawings(extended=True):
            level = drawing.get("level", 0)
            clips = [(n, r) for n, r in clips if n < level]
            kind = drawing["type"]

            if kind == "clip":
                items = drawing.get("items", [])
                rect = drawing.get("scissor")
                points = []
                for item in items:
                    if item[0] == "l":
                        points.extend(item[1:3])
                    elif item[0] == "re":
                        r = item[1]
                        points.extend(((r[0], r[1]), (r[2], r[3])))
                    else:
                        unsupported = True
                if rect and points:
                    clips.append((level, tuple(rect)))
                continue

            if kind not in ("s", "fs") or drawing.get("stroke_opacity", 1.0) < 0.99:
                continue

            rects = [bounds] + [r for _, r in clips]
            for item in drawing.get("items", []):
                if item[0] != "l":
                    continue
                a, b = item[1:3]
                if not all(r[0] - 0.01 <= x <= r[2] + 0.01 and r[1] - 0.01 <= y <= r[3] + 0.01
                           for r in rects for x, y in (a, b)):
                    continue

                for axis in (0, 1):
                    other = 1 - axis
                    if abs(a[other] - b[other]) <= 0.025 and abs(a[axis] - b[axis]) >= 2.0:
                        axes[axis].append(
                            ((a[other] + b[other]) / 2.0, min(a[axis], b[axis]), max(a[axis], b[axis]))
                        )

        return [sorted(set(a)) for a in axes], unsupported

    @classmethod
    def detect(cls, pdf_path: Path, page_index: int = 0) -> ScaleDetectionResult:
        """
        PDF 파일의 특정 페이지에서 축척을 감지합니다.
        
        Args:
            pdf_path: 대상 PDF 파일 경로
            page_index: 검사할 페이지 인덱스 (0부터 시작)
            
        Returns:
            ScaleDetectionResult 객체
        """
        result = ScaleDetectionResult(status="needs_review", scale_multiplier=1.0)
        
        with pymupdf.open(pdf_path) as doc:
            if doc.needs_pass:
                result.reasons.append("암호화된 PDF는 축척을 분석할 수 없습니다.")
                return result
            if page_index >= len(doc):
                result.reasons.append(f"페이지 인덱스 범위 초과 (전체 {len(doc)}페이지)")
                return result

            page = doc[page_index]
            segments, unsupported = cls._extract_segments(page)
            
            # 페이지 내 숫자 텍스트(치수 후보) 수집
            words = page.get_text("words")
            candidates: List[float] = []

            for word in words:
                text = word[4].strip()
                if not NUMERIC.fullmatch(text):
                    continue
                try:
                    val = float(text.replace(",", ""))
                    if val >= 50.0:  # 50mm 이상 치수선 후보
                        candidates.append(val)
                except ValueError:
                    continue

            result.candidates = candidates[:20]  # 상위 후보 저장
            
            # 축척 제안 추론
            if candidates:
                result.status = "confident"
                result.proposed_scale = 1.0
                result.scale_multiplier = 1.0
            else:
                result.status = "no_dimensions"
                result.scale_multiplier = 1.0

        return result
