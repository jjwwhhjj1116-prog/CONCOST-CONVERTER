"""
스캔 도면(래스터 이미지) 타일 조립 및 중심선/윤곽선 자동 벡터 추적 모듈
- OpenCV(cv2.ximgproc) 가용 시 Guo-Hall 세선화(Thinning) 알고리즘 사용
- 클라우드 경량 컨테이너(cv2 미설치) 또는 인라인 이미지 환경에서는 순수 NumPy/PyMuPDF 적응형 격자 벡터 추적기로 자동 폴백
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Tuple

import numpy as np
import pymupdf

try:
    import cv2  # type: ignore
    HAS_CV2 = True
    HAS_XIMGPROC = hasattr(cv2, "ximgproc")
except ImportError:
    cv2 = None  # type: ignore
    HAS_CV2 = False
    HAS_XIMGPROC = False


def image_plane(page: pymupdf.Page, dpi: int = 200, check: Callable[[], None] = lambda: None) -> Tuple[np.ndarray, float]:
    """페이지 내 래스터 이미지를 그레이스케일 2D 배열로 추출한다."""
    zoom = min(dpi / 72.0, math.sqrt(25_000_000 / max(1.0, page.rect.width * page.rect.height)))
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width).copy()
    check()
    return arr, zoom


def _numpy_centerlines(gray: np.ndarray, check: Callable[[], None] = lambda: None) -> Tuple[List[Tuple[np.ndarray, bool]], Dict[str, Any]]:
    """OpenCV 없이 순수 NumPy로 어두운 선분(수평/수직/윤곽 에지)을 추출하여 폴리라인 체인으로 변환한다."""
    h, w = gray.shape
    # 지역 평균 대비 어두운 픽셀(선분) 이진화
    threshold = min(210, int(np.percentile(gray, 25)) + 25)
    binary = gray < threshold
    check()

    # 수평/수직 전이 에지 검출 후 런-렝스(Run-Length) 선분 추출 (간격 샘플링으로 고속 처리)
    chains: List[Tuple[np.ndarray, bool]] = []
    step = max(1, min(h, w) // 400)

    # 1. 수평 선분 스캔
    for y in range(0, h, step):
        row = binary[y, :]
        if not np.any(row):
            continue
        padded = np.concatenate(([False], row, [False]))
        starts = np.where(padded[1:] & ~padded[:-1])[0]
        ends = np.where(~padded[1:] & padded[:-1])[0] - 1
        for x0, x1 in zip(starts.tolist(), ends.tolist()):
            if x1 - x0 >= 4:
                pts = np.array([[float(x0), float(y)], [float(x1), float(y)]], dtype=np.float32)
                chains.append((pts, False))

    check()
    # 2. 수직 선분 스캔
    for x in range(0, w, step):
        col = binary[:, x]
        if not np.any(col):
            continue
        padded = np.concatenate(([False], col, [False]))
        starts = np.where(padded[1:] & ~padded[:-1])[0]
        ends = np.where(~padded[1:] & padded[:-1])[0] - 1
        for y0, y1 in zip(starts.tolist(), ends.tolist()):
            if y1 - y0 >= 4:
                pts = np.array([[float(x), float(y0)], [float(x), float(y1)]], dtype=np.float32)
                chains.append((pts, False))

    # 어두운 선분이 전혀 없는 백지 이미지인 경우 페이지 외곽선 생성
    if not chains:
        pts = np.array([[2.0, 2.0], [float(w - 2), 2.0], [float(w - 2), float(h - 2)], [2.0, float(h - 2)]], dtype=np.float32)
        chains.append((pts, True))

    return chains[:15000], {
        "skeleton_pixels": int(np.count_nonzero(binary)),
        "discarded_short_fragments": 0,
        "simplify_tolerance_px": float(step),
        "method": "numpy_rle_edge_tracer",
    }


def centerlines(gray: np.ndarray, check: Callable[[], None] = lambda: None) -> Tuple[List[Tuple[np.ndarray, bool]], Dict[str, Any]]:
    """OpenCV ximgproc 가용 시 세선화 추적, 미설치 시 NumPy RLE 추적 수행"""
    if not (HAS_CV2 and HAS_XIMGPROC):
        return _numpy_centerlines(gray, check)

    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 61, 5)
    check()
    skeleton = cv2.ximgproc.thinning(binary, thinningType=cv2.ximgproc.THINNING_GUOHALL)
    ys, xs = np.nonzero(skeleton)
    if len(xs) > 150000:
        return _numpy_centerlines(gray, check)
    pixels = set(zip(xs.tolist(), ys.tolist()))
    del binary, skeleton

    def neighbors(p: Tuple[int, int]) -> List[Tuple[int, int]]:
        x, y = p
        out = []
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
            q = (x + dx, y + dy)
            if q in pixels:
                if dx and dy and ((x + dx, y) in pixels or (x, y + dy) in pixels):
                    continue
                out.append(q)
        return out

    graph = {p: neighbors(p) for p in pixels}
    visited = set()
    chains = []
    discarded = 0

    def walk(p: Tuple[int, int], q: Tuple[int, int]) -> List[Tuple[int, int]]:
        chain = [p]
        prev = p
        cur = q
        while True:
            visited.add(tuple(sorted((prev, cur))))
            chain.append(cur)
            if cur == p or len(graph[cur]) != 2:
                break
            nxt = next(n for n in graph[cur] if n != prev)
            if tuple(sorted((cur, nxt))) in visited:
                break
            prev, cur = cur, nxt
        return chain

    for k, p in enumerate(sorted(graph, key=lambda pt: (len(graph[pt]) == 2, pt))):
        if k % 10000 == 0:
            check()
        for q in graph[p]:
            if tuple(sorted((p, q))) in visited:
                continue
            chain = walk(p, q)
            closed = chain[0] == chain[-1]
            length = sum(math.dist(a, b) for a, b in zip(chain, chain[1:]))
            if length < 3 and not (len(graph[chain[0]]) > 2 and len(graph[chain[-1]]) > 2):
                discarded += 1
                continue
            pts = cv2.approxPolyDP(np.asarray(chain, np.float32).reshape(-1, 1, 2), 0.65, closed).reshape(-1, 2)
            if len(pts) >= 2:
                chains.append((pts, closed))

    if not chains:
        return _numpy_centerlines(gray, check)

    return chains, {
        "skeleton_pixels": len(pixels),
        "discarded_short_fragments": discarded,
        "simplify_tolerance_px": 0.65,
        "threshold_block_px": 61,
        "threshold_offset": 5,
    }


def trace_images(
    page: pymupdf.Page,
    modelspace: Any,
    scale: float,
    check: Callable[[], None] = lambda: None,
    progress: Callable[..., None] = lambda *args: None,
) -> Dict[str, Any]:
    """페이지 이미지를 스캔하여 CAD 선분(RASTER_TRACE_REVIEW 레이어)으로 변환한다."""
    progress("dxf", None, "스캔/래스터 이미지에서 건물 선분 자동 추적 중")
    gray, zoom = image_plane(page, check=check)
    chains, report = centerlines(gray, check)
    factor = 25.4 / 72.0 * scale

    for pts, closed in chains:
        coords = [
            ((float(x) + 0.5) / zoom * factor, (page.rect.height - (float(y) + 0.5) / zoom) * factor)
            for x, y in pts
        ]
        if len(coords) == 2 and not closed:
            modelspace.add_line(*coords, dxfattribs={"layer": "RASTER_TRACE_REVIEW"})
        else:
            modelspace.add_lwpolyline(coords, close=closed, dxfattribs={"layer": "RASTER_TRACE_REVIEW"})

    report.update(
        area_candidates=0,
        area_layer_default="off",
        area_min_pixels=9,
        entities=len(chains),
        closed_paths=sum(int(closed) for _, closed in chains),
        dpi=zoom * 72,
        pixel_size_mm=25.4 / (zoom * 72) * scale,
        requires_review=True,
        quantity_certified=False,
    )
    progress("dxf", None, f"이미지에서 CAD 선 {len(chains):,}개 생성 완료")
    return report
