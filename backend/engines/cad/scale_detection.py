"""Conservative dimension-line scale evidence; never changes a PDF or geometry.
AGPL-3.0-or-later. Numbers without confirmed units are proposals only.
"""
from bisect import bisect_left, bisect_right
import math
import re
from statistics import median

import pymupdf

PT_MM = 25.4 / 72
NUMERIC = re.compile(r"(?:[1-9]\d{0,2}(?:,\d{3})+|[1-9]\d{2,})(?:\.\d+)?")


def _segments(page):
    """Retain visible axis-aligned strokes; rectangular clipping only."""
    axes = [[], []]
    clips = []
    unsupported = False
    bounds = tuple(page.rect * page.derotation_matrix)
    for drawing in page.get_cdrawings(extended=True):
        level = drawing.get("level", 0)
        clips = [(n, r) for n, r in clips if n < level]
        kind = drawing["type"]
        if kind == "clip":
            items = drawing.get("items", [])
            rect = drawing.get("scissor")
            # Rectangular straight clipping is the supported detection domain.
            points = []
            for item in items:
                if item[0] == "l":
                    points.extend(item[1:3])
                    if abs(item[1][0]-item[2][0])>.025 and abs(item[1][1]-item[2][1])>.025:
                        unsupported = True
                elif item[0] == "re":
                    r = item[1]
                    points.extend(((r[0], r[1]), (r[2], r[3])))
                else:
                    unsupported = True
            if rect and points:
                xs, ys = {round(p[0], 3) for p in points}, {round(p[1], 3) for p in points}
                if len(xs) != 2 or len(ys) != 2:
                    unsupported = True
                clips.append((level, tuple(rect)))
            else:
                unsupported = True
            continue
        if kind not in ("s", "fs") or drawing.get("stroke_opacity", 1) < .99:
            continue
        rects = [bounds] + [r for _, r in clips]
        for item in drawing.get("items", []):
            if item[0] != "l":
                continue
            a, b = item[1:3]
            if not all(r[0]-.01 <= x <= r[2]+.01 and r[1]-.01 <= y <= r[3]+.01
                       for r in rects for x, y in (a, b)):
                continue
            for axis in (0, 1):
                other = 1-axis
                if abs(a[other]-b[other]) <= .025 and abs(a[axis]-b[axis]) >= 2:
                    axes[axis].append(((a[other]+b[other])/2, min(a[axis],b[axis]), max(a[axis],b[axis])))
    return [sorted(set(a)) for a in axes], unsupported


def detect_scale(pdf, page=1, *, dimension_unit=None):
    """Return confident only for consistent X/Y dimension evidence and known mm.

    scale/proposed_scale is the multiplier relative to paper millimetres.
    dimension_unit='mm' is an explicit user confirmation, not inferred from locale.
    A confident result is a heuristic proposal, not CAD/engineering certification.
    """
    result = dict(status="needs_review", scale=None, proposed_scale=None,
                  nominal_scale=None, eligible_nominal=False,
                  candidates=[], evidence={}, reasons=[])
    if dimension_unit not in (None, "mm"):
        raise ValueError("현재 자동 축척 검증 단위는 mm만 지원합니다.")
    with pymupdf.open(pdf) as document:
        if document.needs_pass:
            result["reasons"].append("암호 PDF는 분석할 수 없습니다.")
            return result
        if not isinstance(page, int) or not 1 <= page <= len(document):
            raise ValueError("분석 페이지 번호가 범위를 벗어났습니다.")
        sheet = document[page-1]
        text = sheet.get_text()
        # Plot timestamps are metadata, not drawing scales (e.g. 1:10:55 AM).
        ratio_text = re.sub(r"\b\d{1,2}:\d{2}:\d{2}(?:\s*[AP]M)?\b|\b\d{1,2}:\d{2}\s*[AP]M\b|\b\d{1,4}/\d{1,2}/\d{1,4}\b",
                            " ",text,flags=re.I)
        declared = sorted({float(n) for n in re.findall(r"(?<![\d.])1\s*[:/]\s*(\d+(?:\.\d+)?)(?![\d.])", ratio_text)})
        unit_note = bool(re.search(r"(?:ALL\s+)?DIMENSIONS?\s+(?:ARE\s+)?(?:IN\s+)?(?:MM|MILLIMET(?:ER|RE)S)\b|단위\s*[:：]?\s*mm\b", text, re.I))
        conflicting_unit = bool(re.search(r"DIMENSIONS?\s+(?:ARE\s+)?(?:IN\s+)?(?:INCH(?:ES)?|FEET|MET(?:ER|RE)S)\b", text, re.I))
        hidden_text = [t["bbox"] for t in sheet.get_texttrace()
                       if t.get("type") == 3 or t.get("opacity", 1) < .99]
        axes, unsupported = _segments(sheet)
        coordinates = [[s[0] for s in a] for a in axes]
        def nearby(axis, c, tolerance):
            return axes[axis][bisect_left(coordinates[axis], c-tolerance):bisect_right(coordinates[axis], c+tolerance)]
        def supported(axis, cross, endpoint, size):
            return any(lo-.3 <= cross <= hi+.3 and hi-lo >= max(2, size*.3)
                       for _,lo,hi in nearby(1-axis, endpoint, .3))
        ambiguous = 0
        used = set()
        numeric_words = 0
        for word in sheet.get_text("words"):
            x0,y0,x1,y1,label = word[:5]
            if any(r[0] <= (x0+x1)/2 <= r[2] and r[1] <= (y0+y1)/2 <= r[3] for r in hidden_text):
                continue
            if not NUMERIC.fullmatch(label):
                continue
            value = float(label.replace(",", ""))
            if not 100 <= value <= 10000000:
                continue
            numeric_words += 1
            axis = 0 if x1-x0 >= y1-y0 else 1
            lo,hi = (x0,x1) if axis == 0 else (y0,y1)
            shortlo,shorthi = (y0,y1) if axis == 0 else (x0,x1)
            size = shorthi-shortlo
            matches = []
            for cross,a,b in nearby(axis, shorthi, max(2, size*.35)):
                length = b-a
                if length < hi-lo or abs((a+b-lo-hi)/2) > max(2, size*.25):
                    continue
                if not (supported(axis,cross,a,size) and supported(axis,cross,b,size)):
                    continue
                ratio = value / length / PT_MM
                if 0 < ratio <= 100000:
                    matches.append((cross,a,b,ratio))
            # Multiple possible dimension lines are not resolved by a convenient scale.
            if len(matches) > 1:
                ambiguous += 1
                continue
            if len(matches) != 1:
                continue
            cross,a,b,ratio = matches[0]
            key = (axis,round(cross,3),round(a,3),round(b,3))
            if key in used:
                continue
            used.add(key)
            endpoints = [[a,cross],[b,cross]] if axis==0 else [[cross,a],[cross,b]]
            result["candidates"].append(dict(label=label,dimension_value=value,
                axis="horizontal" if axis==0 else "vertical", length_pt=b-a,
                scale=ratio, text_bbox_pt=[x0,y0,x1,y1], endpoints_pt=endpoints,
                evidence="centered_numeric_label_and_perpendicular_end_supports"))
        candidates = result["candidates"]
        ratios = [c["scale"] for c in candidates]
        center = median(ratios) if ratios else None
        spread = max(abs(r/center-1) for r in ratios) if ratios else None
        confirmed_unit = dimension_unit == "mm" or unit_note
        # A separate, explicitly confirmed fallback, never a calibrated scale.
        if (not candidates and len(declared)==1 and math.isfinite(declared[0])
                and 0 < declared[0] <= 100000 and confirmed_unit
                and not conflicting_unit and not unsupported and not ambiguous):
            result.update(nominal_scale=declared[0], eligible_nominal=True)
        result["proposed_scale"] = center
        result["evidence"] = dict(page=page,unit="mm" if confirmed_unit else None,
            unit_source="user_confirmed" if dimension_unit else "document_note" if unit_note else "unconfirmed",
            declared_scales=declared, numeric_labels=numeric_words,
            matched_dimensions=len(candidates), ambiguous_labels=ambiguous,
            diagnostic="no_dimension_matches" if not candidates else "dimension_matches_found",
            nominal_scale_source="printed_scale_only_not_dimension_verified" if result["eligible_nominal"] else None,
            maximum_relative_deviation=spread, relative_tolerance=.002,
            limitations=["수평·수직 치수선만 분석", "숫자는 mm 단위 확인 필요", "치수 표기 자체 오류는 판정하지 않음", "페이지 전체 기하의 축척 일관성을 보증하지 않음"])
        reasons = result["reasons"]
        if not candidates:
            reasons.append("숫자와 양단 보조선이 대응되는 수평·수직 치수 근거를 찾지 못했습니다. 관경·측구폭·기기 규격·그리드 번호는 길이 치수로 사용하지 않습니다.")
            if len(declared)==1 and declared[0]>0:
                reasons.append(f"표기 축척 1:{declared[0]:g}은 읽혔지만 실제 길이로 검증된 배율은 아닙니다. 표기 축척 사용 여부를 별도로 확인하세요.")
        elif len(candidates)<4 or len({c["dimension_value"] for c in candidates})<3:
            reasons.append("서로 다른 값 3개를 포함한 치수 4개 이상의 근거가 필요합니다.")
        if candidates and len({c["axis"] for c in candidates})<2:
            reasons.append("가로·세로 두 방향의 치수 근거가 필요합니다.")
        if ratios and max(c["length_pt"] for c in candidates)/min(c["length_pt"] for c in candidates)<2:
            reasons.append("짧은 치수와 긴 치수를 함께 확인해야 합니다.")
        if spread is not None and spread > .002:
            reasons.append("치수별 배율이 일치하지 않습니다. 혼합 축척 또는 잘못 대응된 치수를 확인하세요.")
        # Printed ratios (including timestamps and detail references) do not
        # override measurements. Uniform scaling is checked using real lines.
        notes = []
        if len(declared)>1:
            notes.append("여러 비율 표기가 있으나 배율은 실제 치수선 길이와 치수값으로 계산합니다.")
        if len(declared)==1 and center and (declared[0]<=0 or abs(center/declared[0]-1)>.02):
            notes.append("표기 비율과 측정 배율이 다르므로 실제 치수선 기준 배율을 사용합니다.")
        result["warnings"] = notes
        if unsupported:
            reasons.append("지원 범위를 벗어난 클립 경계가 있어 수동 확인이 필요합니다.")
        if ambiguous:
            reasons.append("여러 치수선에 대응 가능한 숫자가 있어 수동 확인이 필요합니다.")
        if not confirmed_unit:
            reasons.append("도면 치수의 mm 단위를 확인해야 합니다.")
        if conflicting_unit:
            reasons.append("mm 이외의 치수 단위 표기가 있어 수동 확인이 필요합니다.")
        if not reasons:
            reference = max(candidates,key=lambda c:c["length_pt"])
            reference_spread = max(abs(r/reference["scale"]-1) for r in ratios)
            if reference_spread > .002:
                reasons.append("기준 치수선과 나머지 치수선의 배율이 일치하지 않습니다.")
            else:
                result.update(status="confident",scale=reference["scale"],reference_dimension=reference)
                result["evidence"].update(scale_method="reference_endpoints_and_dimension_value",
                    reference_relative_deviation=reference_spread,application_scope="whole_page_uniform_scale")
        return result
