"""PDF vector-to-DXF research prototype. AGPL-3.0-or-later.

MuPDF-generated SVG only; this is intentionally not a general SVG importer.
Coordinates are paper millimetres multiplied by the explicit user scale.
"""
from __future__ import annotations

import argparse
from collections import Counter
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile
import time
import xml.etree.ElementTree as ET

import ezdxf
from ezdxf.colors import rgb2int
from fontTools.pens.recordingPen import RecordingPen
from fontTools.svgLib.path import parse_path
import pymupdf
from shapely.geometry import LineString, Polygon, box
from shapely.ops import polygonize, unary_union

VERSION = "0.1.0-preview"
PT_MM = 25.4 / 72
TOLERANCE_PT = 0.01
IDENTITY = (1., 0., 0., 1., 0., 0.)
NUMBER = r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?"
XLINK = "{http://www.w3.org/1999/xlink}href"


class Cancelled(Exception):
    pass


def matrix(s):
    if not s:
        return IDENTITY
    if not s.startswith("matrix("):
        raise ValueError(f"지원하지 않는 변환: {s}")
    v = tuple(map(float, re.findall(NUMBER, s)))
    if len(v) != 6 or not all(map(math.isfinite, v)):
        raise ValueError("잘못된 변환 행렬")
    return v


def multiply(a, b):
    A, B, C, D, E, F = a
    a, b, c, d, e, f = b
    return (A*a+C*b, B*a+D*b, A*c+C*d, B*c+D*d, A*e+C*f+E, B*e+D*f+F)


def point(m, p):
    x, y = p
    a, b, c, d, e, f = m
    return (a*x+c*y+e, b*x+d*y+f)


@lru_cache(maxsize=2048)
def commands(data):
    pen = RecordingPen()
    parse_path(data, pen)
    return pen.value


def flatten(data, transform, tolerance=TOLERANCE_PT):
    """Adaptive cubic subdivision, with a conservative control-polygon bound."""
    result, current = [], []

    def curve(a, b, c, d, depth=0):
        dx, dy = d[0]-a[0], d[1]-a[1]
        length = math.hypot(dx, dy)
        if length < 1e-15:
            error = max(math.dist(a, b), math.dist(a, c))
        else:
            # Distance to the finite chord, not the infinite line: detects loops.
            def distance(p):
                t = max(0., min(1., ((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(length*length)))
                return math.dist(p, (a[0]+t*dx, a[1]+t*dy))
            error = max(distance(b), distance(c))
        if error <= tolerance:
            current.append(d)
            return
        if depth >= 20:
            raise ValueError("곡선 근사 한계 초과")
        mid = lambda p, q: ((p[0]+q[0])/2, (p[1]+q[1])/2)
        ab, bc, cd = mid(a,b), mid(b,c), mid(c,d)
        abc, bcd = mid(ab,bc), mid(bc,cd)
        center = mid(abc,bcd)
        curve(a,ab,abc,center,depth+1)
        curve(center,bcd,cd,d,depth+1)

    for op, args in commands(data):
        pts = [point(transform, p) for p in args]
        if op == "moveTo":
            if current:
                result.append(current)
            current = [pts[0]]
        elif op == "lineTo":
            current.extend(pts)
        elif op == "curveTo":
            curve(current[-1], *pts)
        elif op == "qCurveTo" and len(pts) == 2:
            a, b, d = current[-1], *pts
            curve(a, (a[0]+2*(b[0]-a[0])/3,a[1]+2*(b[1]-a[1])/3),
                  (d[0]+2*(b[0]-d[0])/3,d[1]+2*(b[1]-d[1])/3), d)
        elif op == "closePath":
            if current and current[-1] != current[0]:
                current.append(current[0])
            result.append(current)
            current = []
        elif op == "endPath":
            result.append(current)
            current = []
        else:
            raise ValueError(f"지원하지 않는 경로 명령: {op}")
    if current:
        result.append(current)
    return [p for p in result if len(p) > 1]


def winding(p, ring):
    x, y = p
    n = 0
    for a, b in zip(ring, ring[1:]+ring[:1]):
        side = (b[0]-a[0])*(y-a[1])-(x-a[0])*(b[1]-a[1])
        if a[1] <= y < b[1] and side > 0:
            n += 1
        elif b[1] <= y < a[1] and side < 0:
            n -= 1
    return n


def filled_geometry(paths, evenodd=False):
    rings = [p if p[0] == p[-1] else p+[p[0]] for p in paths if len(p) >= 3]
    if not rings:
        return Polygon()
    # Polygonize then classify each face using the original PDF winding rule.
    faces = polygonize(unary_union([LineString(r) for r in rings]))
    selected = []
    for face in faces:
        rp = face.representative_point()
        n = sum(winding((rp.x, rp.y), r) for r in rings)
        if (n % 2 != 0) if evenodd else (n != 0):
            selected.append(face)
    return unary_union(selected)


def pieces(geom, kind):
    if geom.is_empty:
        return
    if geom.geom_type == kind:
        yield geom
    elif hasattr(geom, "geoms"):
        for item in geom.geoms:
            yield from pieces(item, kind)


def color(s):
    if s == "none":
        return None
    if s.startswith("#"):
        s = s[1:]
        if len(s) == 3:
            s = "".join(c*2 for c in s)
        return tuple(int(s[i:i+2],16) for i in (0,2,4))
    if s == "black":
        return (0,0,0)
    if s == "white":
        return (255,255,255)
    raise ValueError(f"지원하지 않는 색상: {s}")


def read_svg_definitions(svg, check=lambda: None):
    """Index every definition and image ID without retaining the complete SVG.

    MuPDF can reuse an image with <use>, including images defined outside defs.
    Only clipPath subtrees need to survive until their end event.
    """
    paths, clips, images, ids = {}, {}, set(), set()
    stack, uses = [], []
    total_paths = direct_images = elements = 0
    for event, e in ET.iterparse(svg, events=("start", "end")):
        tag = e.tag.rsplit("}", 1)[-1]
        if event == "start":
            stack.append((e, tag))
            ident = e.get("id")
            if ident:
                if ident in ids:
                    raise ValueError(f"중복 SVG 정의: {ident}")
                ids.add(ident)
                if tag == "path":
                    paths[ident] = e.get("d", "")
                elif tag == "image":
                    images.add(ident)
            in_defs = any(t == "defs" for _, t in stack)
            if not in_defs:
                if tag == "path":
                    total_paths += 1
                elif tag == "image":
                    direct_images += 1
                elif tag == "use":
                    uses.append(e.get(XLINK, e.get("href", "")))
        else:
            if tag == "clipPath":
                if len(e) != 1 or e[0].tag.rsplit("}", 1)[-1] != "path":
                    raise ValueError("복합 SVG 클립은 아직 지원하지 않습니다.")
                child = e[0]
                clips[e.get("id")] = filled_geometry(
                    flatten(child.get("d"), matrix(child.get("transform"))),
                    child.get("clip-rule") == "evenodd")
            stack.pop()
            if not any(t == "clipPath" for _, t in stack):
                e.clear()
                if stack:
                    stack[-1][0].remove(e)
            elements += 1
            if elements % 25000 == 0:
                check()
    image_uses = 0
    for href in uses:
        if not href.startswith("#") or (href[1:] not in paths and href[1:] not in images):
            raise ValueError(f"SVG 참조 정의를 찾을 수 없거나 지원하지 않습니다: {href}")
        image_uses += href[1:] in images
    return paths, clips, images, total_paths, direct_images + image_uses, image_uses


def convert(source, output, page_number=1, scale=1., progress=lambda s: None,
            cancelled=lambda: False, details=lambda stage, percent, message: None, raster_trace=False):
    source, output = Path(source), Path(output)
    if not math.isfinite(scale) or not 0 < scale <= 100000:
        raise ValueError("축척 배수는 0 초과 100000 이하의 유한 숫자여야 합니다.")
    if output.suffix.lower() != ".dxf":
        raise ValueError("출력 확장자는 .dxf여야 합니다.")
    if source.resolve() == output.resolve() or output.exists():
        raise FileExistsError("원본 또는 기존 결과를 덮어쓸 수 없습니다.")
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    factor = PT_MM * scale
    report = dict(version=VERSION, input_name=source.name, page=page_number,
                  scale=scale, unit="mm", scale_mode="explicit_nominal_multiplier",
                  tolerance_paper_pt=TOLERANCE_PT,
                  curve_tolerance_output_mm=TOLERANCE_PT*factor,
                  warnings=[], cad_application_verified=False)
    report["input_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    warnings = set()
    counts = Counter()
    doc = ezdxf.new("R2013")
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    for name in ("PDF_LINES", "PDF_FILLS", "TEXT_OUTLINE", "PDF_IMAGES", "RASTER_TRACE_REVIEW", "RASTER_AREAS_REVIEW"):
        doc.layers.new(name)

    def check():
        if cancelled():
            raise Cancelled("사용자가 변환을 취소했습니다.")

    with pymupdf.open(source) as pdf, tempfile.TemporaryDirectory(prefix="pdfdxf-") as tmp:
        if pdf.needs_pass:
            raise ValueError("암호 PDF는 잠금 해제된 사본을 선택하세요.")
        if not 1 <= page_number <= len(pdf):
            raise ValueError(f"페이지는 1~{len(pdf)} 범위여야 합니다.")
        page = pdf[page_number-1]
        width, height = page.rect.width, page.rect.height
        report.update(page_count=len(pdf), paper_size_mm=[width*PT_MM,height*PT_MM],
                      rotation=page.rotation)
        progress("PDF 문자 윤곽선·벡터 추출 중")
        details("pdf", None, "PDF 벡터·문자 추출 중")
        check()
        svg = Path(tmp)/"page.svg"
        svg.write_text(page.get_svg_image(text_as_path=True),encoding="utf-8")
        report["intermediate_svg_bytes"] = svg.stat().st_size
        check()
        paths_by_id, clips, image_ids, total_paths, image_occurrences, image_uses = read_svg_definitions(svg, check)
        image_info = page.get_image_info()
        if len(image_info) != image_occurrences:
            raise ValueError("SVG 이미지 참조와 PDF 이미지 개수가 다릅니다. 이미지 누락 방지를 위해 중단합니다.")
        report.update(svg_image_occurrences=image_occurrences, svg_image_references=image_uses)
        root_clip = box(0,0,width,height)

        def xy(p):
            return (p[0]*factor,(height-p[1])*factor)

        def emit(data, attrs, transform, clip, text=False):
            paths = flatten(data,transform)
            if not paths:
                return
            bounds = clip.bounds
            if not bounds:
                return
            all_inside = all(bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]
                             for p in paths for x,y in p) and clip.equals(box(*bounds))
            fill = color(attrs.get("fill","black"))
            stroke = color(attrs.get("stroke","none"))
            if fill is not None:
                geom = filled_geometry(paths,attrs.get("fill-rule")=="evenodd")
                if not all_inside:
                    geom = geom.intersection(clip)
                for poly in pieces(geom,"Polygon"):
                    hatch = msp.add_hatch(color=7,dxfattribs={
                        "layer":"TEXT_OUTLINE" if text else "PDF_FILLS", "true_color":rgb2int(fill)})
                    hatch.paths.add_polyline_path([xy(p) for p in poly.exterior.coords],is_closed=True,flags=1)
                    for ring in poly.interiors:
                        hatch.paths.add_polyline_path([xy(p) for p in ring.coords],is_closed=True,flags=0)
                    counts["hatches"] += 1
            if stroke is not None:
                # PDF stroke widths are paper widths; DXF physical lineweight is kept.
                a,b,c,d,_,_ = transform
                if abs(math.hypot(a,b)-math.hypot(c,d)) > 1e-5:
                    warnings.add("비등방 변환의 선폭은 평균값으로 근사했습니다.")
                w = float(attrs.get("stroke-width","1"))*(math.hypot(a,b)+math.hypot(c,d))/2
                lineweights = (0,5,9,13,15,18,20,25,30,35,40,50,53,60,70,80,90,100,106,120,140,158,200,211)
                lw = min(lineweights,key=lambda x: abs(x-w*PT_MM*100))
                attrib = dict(layer="PDF_LINES",true_color=rgb2int(stroke),lineweight=lw)
                for path in paths:
                    if all_inside:
                        segments = [path]
                    else:
                        segments = [list(line.coords) for line in pieces(LineString(path).intersection(clip),"LineString")]
                    for pts in segments:
                        if len(pts) == 2:
                            msp.add_line(xy(pts[0]),xy(pts[1]),dxfattribs=attrib)
                            counts["lines"] += 1
                        else:
                            closed = pts[0] == pts[-1]
                            msp.add_lwpolyline([xy(p) for p in (pts[:-1] if closed else pts)],
                                              close=closed,dxfattribs=attrib)
                            counts["polylines"] += 1

        progress("CAD 선·문자 윤곽선 생성 중")
        details("dxf", 0, "DXF 객체 생성 시작")
        # Stack holds inherited paint, transform, clipping and whether this is a definition.
        stack = []
        root = None
        for event, e in ET.iterparse(svg,events=("start","end")):
            tag = e.tag.rsplit("}",1)[-1]
            if event == "start":
                if root is None:
                    root = e
                if stack:
                    parent, trans, paint, clip, skip = stack[-1]
                    paint = paint.copy()
                else:
                    trans, paint, clip, skip = IDENTITY, {}, root_clip, False
                trans = multiply(trans,matrix(e.get("transform")))
                for k in ("fill","stroke","stroke-width","fill-rule"):
                    if k in e.attrib:
                        paint[k] = e.get(k)
                skip = skip or tag == "defs"
                if not skip and e.get("clip-path"):
                    ref = e.get("clip-path")[5:-1]
                    if ref not in clips:
                        raise ValueError("알 수 없는 클립 경로")
                    if trans != IDENTITY:
                        from shapely.affinity import affine_transform
                        a,b,c,d,f,g = trans
                        current_clip = affine_transform(clips[ref],(a,c,b,d,f,g))
                    else:
                        current_clip = clips[ref]
                    clip = clip.intersection(current_clip)
                if not skip:
                    for key in ("opacity","fill-opacity","stroke-opacity","stroke-dasharray","filter","mask"):
                        if key in e.attrib:
                            warnings.add(f"SVG {key} 속성은 완전 재현되지 않을 수 있습니다.")
                stack.append((e,trans,paint,clip,skip))
            else:
                _,trans,paint,clip,skip = stack.pop()
                if not skip:
                    if tag == "path":
                        emit(e.get("d",""),paint,trans,clip)
                        counts["source_paths"] += 1
                    elif tag == "use":
                        ref = e.get(XLINK,e.get("href","")).lstrip("#")
                        if ref in image_ids:
                            # Every raster occurrence is preserved from PDF below,
                            # including the referenced image's transform and mask.
                            counts["image_references"] += 1
                        else:
                            if ref not in paths_by_id:
                                raise ValueError(f"SVG 참조 정의를 찾을 수 없습니다: {ref}")
                            if e.get("x") or e.get("y"):
                                trans = multiply(trans,(1,0,0,1,float(e.get("x",0)),float(e.get("y",0))))
                            emit(paths_by_id[ref],paint,trans,clip,True)
                            counts["glyphs"] += 1
                    elif tag not in ("svg","g","image"):
                        raise ValueError(f"지원하지 않는 SVG 요소: {tag}")
                    if counts["source_paths"] and counts["source_paths"] % 25000 == 0 and tag == "path":
                        check()
                        progress(f"벡터 경로 {counts['source_paths']:,}개 처리")
                        details("dxf", min(100, counts['source_paths'] / max(1,total_paths)*100),
                                f"벡터 경로 {counts['source_paths']:,} / {total_paths:,}개")
                e.clear()
                if stack:
                    stack[-1][0].remove(e)
        check()
        if raster_trace and image_info:
            from raster_trace import trace_images
            report['raster_trace'] = trace_images(page, msp, scale, check, details)
            counts['traced_entities'] = report['raster_trace']['entities']
            doc.layers.get('PDF_IMAGES').off()
            doc.layers.get('RASTER_AREAS_REVIEW').off()
            warnings.add('이미지 추적선은 RASTER_TRACE_REVIEW 레이어입니다. 길이·연결·폐합을 검수 후 적산하세요. 원본 이미지 레이어는 꺼져 있습니다.')
        if not sum(counts[k] for k in ("lines","polylines","hatches","traced_entities")):
            raise ValueError("편집 가능한 벡터가 없습니다. 스캔 도면 자동 추적은 미지원입니다.")
        # Preserve raster logos as appearance-cropped PNGs. This also handles soft masks.
        # ponytail: per-image crops may include overlapping vectors; report, don't imply vectorization.
        assets = []
        for i, item in enumerate(image_info):
            r = (pymupdf.Rect(item["bbox"]) * page.rotation_matrix) & page.rect
            if r.is_empty:
                continue
            asset_name = f"{output.stem}_image_{i+1:02}.png"
            asset = Path(tmp)/asset_name
            page.get_pixmap(matrix=pymupdf.Matrix(3,3),clip=r,alpha=False).save(asset)
            pm = pymupdf.Pixmap(asset)
            idef = doc.add_image_def(filename=asset_name,size_in_pixel=(pm.width,pm.height))
            msp.add_image(idef,insert=xy((r.x0,r.y1)),size_in_units=(r.width*factor,r.height*factor),
                          dxfattribs={"layer":"PDF_IMAGES"})
            assets.append((asset,output.parent/asset_name))
            counts["images"] += 1
        if assets:
            warnings.add("이미지는 페이지 외형을 잘라 PNG 참조로 보존했습니다. DXF와 함께 보관하세요.")
        warnings.add("문자는 윤곽선 HATCH입니다. 문자 검색·내용 편집은 불가능합니다.")
        warnings.add("선폭은 DXF 표준 선가중치로 근사하며 선 끝·접합 모양은 CAD에 따라 다를 수 있습니다.")
        if page.first_annot:
            warnings.add("PDF 주석은 벡터 변환 대상에 포함되지 않습니다.")
        doc.header["$LWDISPLAY"] = True
        doc.set_raster_variables(frame=0,quality=1,units="mm")
        doc.header["$INSBASE"] = (0,0,0)
        doc.set_modelspace_vport(height=height*factor,center=(width*factor/2,height*factor/2))
        progress("DXF 구조 검사·저장 중")
        details("dxf", None, "DXF 객체 생성 완료 · 구조 검사·파일 저장 중")
        check()
        audit = doc.audit()
        report["audit_errors"] = len(audit.errors)
        report["audit_fixes"] = len(audit.fixes)
        if audit.errors or audit.fixes:
            raise ValueError("DXF 구조 검사에서 오류 또는 자동 수정이 발견되었습니다.")
        candidate = Path(tmp)/"result.dxf"
        doc.saveas(candidate)
        check()
        report["entities"] = len(msp)
        report["counts"] = dict(counts)
        report["warnings"] = sorted(warnings)
        report["seconds"] = round(time.monotonic()-started,2)
        report["status"] = "converted_with_warnings"
        report_path = output.with_suffix(".report.json")
        report_file = Path(tmp)/"report.json"
        report_file.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        exports = assets+[(report_file,report_path),(candidate,output)]
        created = []
        try:
            for src, dst in exports:
                # Exclusive create protects against output collisions, including races.
                with dst.open("xb") as out:
                    created.append(dst)
                    with src.open("rb") as inp:
                        import shutil
                        shutil.copyfileobj(inp,out,1024*1024)
        except Exception:
            for dst in created:
                dst.unlink(missing_ok=True)
            raise
    progress(f"변환 완료 · {report['entities']:,}개 객체 · 경고 {len(warnings)}건")
    return report


def main():
    parser = argparse.ArgumentParser(description="PDF to editable DXF geometry (preview)")
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--page",type=int,default=1)
    parser.add_argument("--scale",type=float,default=1.)
    args = parser.parse_args()
    convert(args.input,args.output,args.page,args.scale,progress=lambda s: print(s,flush=True))


if __name__ == "__main__":
    main()
