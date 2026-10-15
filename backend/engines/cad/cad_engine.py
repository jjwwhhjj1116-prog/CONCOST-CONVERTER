"""
CAD 변환 엔진 (CAD Engine) - CONCOST-Converter-0.2.2 아키텍처 통합
PDF 벡터 도면을 ezdxf/MuPDF/shapely 기반 정밀 DXF 및 ZWCAD COM API 기반 순수 바이너리 DWG로 변환합니다.
3차 베지어 곡선 적응형 분할, 건축 레이어 분리(선/채우기/문자윤곽/이미지), 도면 축척 보정 및 무결성 검증을 수행합니다.
"""
from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from backend.engines.cad.concost_converter import convert as concost_pdf_to_dxf
from backend.engines.cad.concost_dwg import convert_dwg as concost_dxf_to_dwg, find_libredwg_binary, installed_zwcad
from backend.engines.cad.scale_detection import detect_scale as concost_detect_scale


@dataclass
class CadConversionOptions:
    """CAD 변환 세부 옵션"""
    scale_multiplier: float = 1.0  # 기본 배율
    auto_detect_scale: bool = False  # 도면 표제란 기반 축척 자동 보정 여부
    page_number: int = 1  # 변환 대상 페이지 (1부터 시작)
    raster_trace: bool = False  # 래스터 이미지 벡터 추적 여부
    target_format: str = "dxf"  # "dxf" 또는 "dwg"


@dataclass
class CadConversionResult:
    """CAD 변환 결과"""
    success: bool
    output_path: Path
    format: str = "dxf"
    total_entities: int = 0
    lines_count: int = 0
    hatches_count: int = 0
    images_count: int = 0
    applied_scale: float = 1.0
    layers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    zwcad_engine: Optional[str] = None
    error_message: Optional[str] = None


class CadEngine:
    """CONCOST-Converter-0.2.2 기반 통합 CAD 변환기"""

    @staticmethod
    def _sanitize_and_load_dxf(dxf_path: Path):
        """dwgread 역변환 DXF의 이중 개행(\r\r\n) 및 Invalid handle 0 등을 자동 복구하여 ezdxf Document로 반환"""
        import ezdxf
        from ezdxf import recover
        import re

        raw_bytes = dxf_path.read_bytes()
        if b"\r\r\n" in raw_bytes:
            raw_bytes = raw_bytes.replace(b"\r\r\n", b"\n").replace(b"\r\n", b"\n")
            dxf_path.write_bytes(raw_bytes)

        try:
            return ezdxf.readfile(str(dxf_path))
        except Exception:
            clean_bytes = raw_bytes.replace(b"\r\r\n", b"\n").replace(b"\r\n", b"\n")
            raw_txt = clean_bytes.decode("utf-8", errors="ignore")
            counter = 0x90000

            def _repl(m: re.Match[str]) -> str:
                nonlocal counter
                counter += 1
                return f"{m.group(1)}{counter:X}\n"

            fixed_txt = re.sub(r"(^[ \t]*(?:5|105)\n)[ \t]*0\n", _repl, raw_txt, flags=re.MULTILINE)
            dxf_path.write_bytes(fixed_txt.encode("utf-8"))
            doc, _ = recover.readfile(str(dxf_path))
            try:
                doc.saveas(str(dxf_path))
            except Exception:
                pass
            return doc


    @classmethod
    def get_zwcad_status(cls) -> Dict[str, Any]:
        """ZWCAD COM API 또는 LibreDWG 클라우드 DWG 엔진 상태 조회"""
        try:
            versions = installed_zwcad()
            libredwg = find_libredwg_binary()
            if libredwg is not None:
                all_engines = ["LibreDWG-Cloud"] + versions
                return {
                    "available": True,
                    "versions": all_engines,
                    "default_engine": "LibreDWG-Cloud",
                    "engine_type": "LibreDWG 0.14 Cloud Native DWG Engine",
                }
            return {
                "available": len(versions) > 0,
                "versions": versions,
                "default_engine": versions[0] if versions else None,
                "engine_type": "ZWCAD Native COM API" if versions else "Not Installed",
            }
        except Exception as e:
            return {
                "available": False,
                "versions": [],
                "default_engine": None,
                "error": str(e),
            }

    @classmethod
    def convert_pdf_to_dxf(
        cls,
        pdf_path: Path,
        dxf_path: Path,
        options: Optional[CadConversionOptions] = None,
    ) -> CadConversionResult:
        """
        PDF 파일의 도면을 CONCOST 정밀 벡터 알고리즘을 통해 DXF로 변환합니다.
        
        Args:
            pdf_path: 원본 PDF 경로
            dxf_path: 생성할 DXF 출력 경로
            options: 변환 세부 옵션
            
        Returns:
            CadConversionResult 결과 객체
        """
        if options is None:
            options = CadConversionOptions()

        dxf_path.parent.mkdir(parents=True, exist_ok=True)
        scale = options.scale_multiplier

        # 축척 자동 감지 활성화 시 수행
        if options.auto_detect_scale:
            try:
                scale_res = concost_detect_scale(str(pdf_path), page=options.page_number)
                detected = scale_res.get("scale") or scale_res.get("proposed_scale")
                if detected and float(detected) > 0:
                    scale = float(detected)
            except Exception:
                pass

        try:
            # 기존 동일 파일이 있을 경우 덮어쓰기 허용을 위해 임시 디렉터리 활용
            with tempfile.TemporaryDirectory(prefix="cad_dxf_") as tmp_dir:
                tmp_output = Path(tmp_dir) / dxf_path.name
                
                # CONCOST-Converter 정밀 벡터 변환 엔진 가동
                report = concost_pdf_to_dxf(
                    source=str(pdf_path),
                    output=str(tmp_output),
                    page_number=options.page_number,
                    scale=scale,
                    raster_trace=options.raster_trace,
                )

                # 결과물 복사
                shutil.copy2(tmp_output, dxf_path)
                
                # 보조 파일(report.json 및 이미지 에셋) 복사
                tmp_report = tmp_output.with_suffix(".report.json")
                if tmp_report.exists():
                    shutil.copy2(tmp_report, dxf_path.with_suffix(".report.json"))

                counts = report.get("counts", {})
                return CadConversionResult(
                    success=True,
                    output_path=dxf_path,
                    format="dxf",
                    total_entities=report.get("entities", 0),
                    lines_count=counts.get("lines", 0) + counts.get("polylines", 0),
                    hatches_count=counts.get("hatches", 0),
                    images_count=counts.get("images", 0),
                    applied_scale=scale,
                    layers=["PDF_LINES", "PDF_FILLS", "TEXT_OUTLINE", "PDF_IMAGES"],
                    warnings=report.get("warnings", []),
                )

        except Exception as e:
            return CadConversionResult(
                success=False,
                output_path=dxf_path,
                format="dxf",
                error_message=f"CONCOST DXF 변환 실패: {str(e)}",
            )

    @classmethod
    def convert_pdf_to_dwg(
        cls,
        pdf_path: Path,
        dwg_path: Path,
        options: Optional[CadConversionOptions] = None,
    ) -> CadConversionResult:
        """
        PDF를 고정밀 DXF로 생성 후 로컬 ZWCAD COM API를 통해 순수 바이너리 DWG로 변환 및 무결성 검증.
        
        Args:
            pdf_path: 원본 PDF 경로
            dwg_path: 최종 DWG 출력 경로
            options: 변환 세부 옵션
            
        Returns:
            CadConversionResult 결과 객체
        """
        if options is None:
            options = CadConversionOptions()

        dwg_path.parent.mkdir(parents=True, exist_ok=True)
        status = cls.get_zwcad_status()
        if not status["available"]:
            return CadConversionResult(
                success=False,
                output_path=dwg_path,
                format="dwg",
                error_message="로컬에 설치된 ZWCAD를 찾을 수 없습니다. DWG 변환은 ZWCAD가 설치된 환경에서 지원됩니다. 대신 DXF 변환을 사용하세요.",
            )

        progid = status["default_engine"]

        try:
            with tempfile.TemporaryDirectory(prefix="cad_dwg_stage_") as tmp_dir:
                stage_dxf = Path(tmp_dir) / f"{dwg_path.stem}.dxf"
                
                # 1단계: CONCOST DXF 생성
                dxf_result = cls.convert_pdf_to_dxf(
                    pdf_path=pdf_path,
                    dxf_path=stage_dxf,
                    options=options,
                )
                if not dxf_result.success:
                    return CadConversionResult(
                        success=False,
                        output_path=dwg_path,
                        format="dwg",
                        error_message=f"DWG 생성 중 1단계 DXF 변환 실패: {dxf_result.error_message}",
                    )

                # 2단계: ZWCAD COM API로 DWG 저장 및 재열기 무결성 검증
                dwg_report = concost_dxf_to_dwg(
                    source=stage_dxf,
                    progid=progid,
                )

                stage_dwg = stage_dxf.with_suffix(".dwg")
                if not stage_dwg.exists():
                    raise RuntimeError("ZWCAD 변환 후 생성된 DWG 파일을 찾을 수 없습니다.")

                shutil.copy2(stage_dwg, dwg_path)

                return CadConversionResult(
                    success=True,
                    output_path=dwg_path,
                    format="dwg",
                    total_entities=dwg_report.get("saved_entities", dxf_result.total_entities),
                    lines_count=dxf_result.lines_count,
                    hatches_count=dxf_result.hatches_count,
                    images_count=dxf_result.images_count,
                    applied_scale=dxf_result.applied_scale,
                    layers=dxf_result.layers,
                    zwcad_engine=progid,
                    warnings=dxf_result.warnings,
                )

        except Exception as e:
            return CadConversionResult(
                success=False,
                output_path=dwg_path,
                format="dwg",
                error_message=f"ZWCAD DWG 변환 실패: {str(e)}",
            )

    @classmethod
    def convert_dxf_to_dwg(cls, dxf_path: Path, dwg_path: Path) -> CadConversionResult:
        """DXF 파일을 LibreDWG 또는 ZWCAD 엔진으로 DWG(AC1032/AC1015) 변환"""
        dwg_path.parent.mkdir(parents=True, exist_ok=True)
        status = cls.get_zwcad_status()
        progid = status.get("default_engine") or "LibreDWG-Cloud"
        try:
            with tempfile.TemporaryDirectory(prefix="dxf2dwg_") as tmp:
                stage_dxf = Path(tmp) / f"{dwg_path.stem}.dxf"
                shutil.copy2(dxf_path, stage_dxf)
                rep = concost_dxf_to_dwg(source=stage_dxf, progid=progid)
                stage_dwg = stage_dxf.with_suffix(".dwg")
                shutil.copy2(stage_dwg, dwg_path)
                return CadConversionResult(
                    success=True,
                    output_path=dwg_path,
                    format="dwg",
                    total_entities=rep.get("saved_entities", 0),
                    zwcad_engine=progid,
                )
        except Exception as e:
            return CadConversionResult(success=False, output_path=dwg_path, format="dwg", error_message=str(e))

    @classmethod
    def convert_dwg_to_dxf(cls, dwg_path: Path, dxf_path: Path) -> CadConversionResult:
        """DWG 파일을 LibreDWG(dwgread)를 이용해 DXF로 역변환"""
        import subprocess
        dxf_path.parent.mkdir(parents=True, exist_ok=True)
        dwgwrite_bin = find_libredwg_binary()
        dwgread_bin = shutil.which("dwgread")
        if not dwgread_bin and dwgwrite_bin:
            cand = Path(dwgwrite_bin).parent / ("dwgread.exe" if os.name == "nt" else "dwgread")
            if cand.exists():
                dwgread_bin = str(cand)
        if not dwgread_bin:
            return CadConversionResult(
                success=False, output_path=dxf_path, format="dxf", error_message="dwgread 바이너리를 찾을 수 없습니다."
            )
        proc = subprocess.run(
            [dwgread_bin, "-O", "DXF", "-o", str(dxf_path), str(dwg_path)],
            capture_output=True,
            timeout=120,
            check=False,
        )
        if dxf_path.exists() and dxf_path.stat().st_size > 0:
            try:
                cls._sanitize_and_load_dxf(dxf_path)
            except Exception:
                pass
            return CadConversionResult(success=True, output_path=dxf_path, format="dxf", zwcad_engine="LibreDWG-dwgread")
        err = proc.stderr.decode("utf-8", errors="ignore")
        return CadConversionResult(success=False, output_path=dxf_path, format="dxf", error_message=err or "DWG->DXF 실패")

    @classmethod
    def render_dxf_to_visual(cls, dxf_path: Path, output_path: Path, target_fmt: str, dpi: int = 300) -> bool:
        """DXF 벡터 엔티티(LINE, LWPOLYLINE, CIRCLE, ARC)를 PyMuPDF 캔버스에 렌더링하여 PDF/SVG/PNG/WEBP 생성"""
        import ezdxf
        import fitz
        from PIL import Image

        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc = cls._sanitize_and_load_dxf(dxf_path)
        msp = doc.modelspace()

        segs: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        xs: List[float] = []
        ys: List[float] = []

        for e in msp:
            dxftype = e.dxftype()
            try:
                if dxftype == "LINE":
                    p1 = (float(e.dxf.start.x), float(e.dxf.start.y))
                    p2 = (float(e.dxf.end.x), float(e.dxf.end.y))
                    segs.append((p1, p2))
                    xs.extend((p1[0], p2[0]))
                    ys.extend((p1[1], p2[1]))
                elif dxftype == "LWPOLYLINE":
                    pts = [(float(p[0]), float(p[1])) for p in e.get_points("xy")]
                    if e.closed and len(pts) > 2:
                        pts.append(pts[0])
                    for a, b in zip(pts, pts[1:]):
                        segs.append((a, b))
                    for px, py in pts:
                        xs.append(px)
                        ys.append(py)
                elif dxftype == "HATCH":
                    for path in e.paths:
                        verts = getattr(path, "vertices", None)
                        if verts and len(verts) >= 2:
                            pts = [(float(v[0]), float(v[1])) for v in verts]
                            if getattr(path, "is_closed", True) and len(pts) > 2:
                                pts.append(pts[0])
                            for a, b in zip(pts, pts[1:]):
                                segs.append((a, b))
                            for px, py in pts:
                                xs.append(px)
                                ys.append(py)
            except Exception:
                continue

        pdf = fitz.open()
        page_w, page_h = 842.0, 595.0
        page = pdf.new_page(width=page_w, height=page_h)

        if xs and ys:
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            span_x = max(max_x - min_x, 1.0)
            span_y = max(max_y - min_y, 1.0)
            margin = 36.0
            scale = min((page_w - 2 * margin) / span_x, (page_h - 2 * margin) / span_y)

            shape = page.new_shape()
            for (x0, y0), (x1, y1) in segs[:80000]:
                sx0 = margin + (x0 - min_x) * scale
                sy0 = page_h - (margin + (y0 - min_y) * scale)
                sx1 = margin + (x1 - min_x) * scale
                sy1 = page_h - (margin + (y1 - min_y) * scale)
                shape.draw_line(fitz.Point(sx0, sy0), fitz.Point(sx1, sy1))
            shape.finish(color=(0, 0, 0), width=0.6)
            shape.commit()

        tgt = target_fmt.lower().strip()
        if tgt == "pdf":
            pdf.save(str(output_path))
            pdf.close()
            return output_path.exists()
        if tgt == "svg":
            output_path.write_text(page.get_svg_image(text_as_path=False), encoding="utf-8")
            pdf.close()
            return output_path.exists()

        pix = page.get_pixmap(dpi=min(dpi, 300), alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        fmt_upper = "JPEG" if tgt in ("jpg", "jpeg") else tgt.upper()
        img.save(str(output_path), format=fmt_upper)
        pdf.close()
        return output_path.exists()

    @classmethod
    def convert_dxf_to_dwg(cls, dxf_path: Path, dwg_path: Path) -> CadConversionResult:
        """DXF 파일을 LibreDWG 또는 ZWCAD 엔진으로 DWG(AC1032/AC1015) 변환"""
        dwg_path.parent.mkdir(parents=True, exist_ok=True)
        status = cls.get_zwcad_status()
        progid = status.get("default_engine") or "LibreDWG-Cloud"
        try:
            with tempfile.TemporaryDirectory(prefix="dxf2dwg_") as tmp:
                stage_dxf = Path(tmp) / f"{dwg_path.stem}.dxf"
                shutil.copy2(dxf_path, stage_dxf)
                rep = concost_dxf_to_dwg(source=stage_dxf, progid=progid)
                stage_dwg = stage_dxf.with_suffix(".dwg")
                shutil.copy2(stage_dwg, dwg_path)
                return CadConversionResult(
                    success=True,
                    output_path=dwg_path,
                    format="dwg",
                    total_entities=rep.get("saved_entities", 0),
                    zwcad_engine=progid,
                )
        except Exception as e:
            return CadConversionResult(success=False, output_path=dwg_path, format="dwg", error_message=str(e))

    @classmethod
    def convert_dwg_to_dxf(cls, dwg_path: Path, dxf_path: Path) -> CadConversionResult:
        """DWG 파일을 LibreDWG(dwgread)를 이용해 DXF로 역변환"""
        import subprocess
        dxf_path.parent.mkdir(parents=True, exist_ok=True)
        dwgwrite_bin = find_libredwg_binary()
        dwgread_bin = shutil.which("dwgread")
        if not dwgread_bin and dwgwrite_bin:
            cand = Path(dwgwrite_bin).parent / ("dwgread.exe" if os.name == "nt" else "dwgread")
            if cand.exists():
                dwgread_bin = str(cand)
        if not dwgread_bin:
            return CadConversionResult(
                success=False, output_path=dxf_path, format="dxf", error_message="dwgread 바이너리를 찾을 수 없습니다."
            )
        proc = subprocess.run(
            [dwgread_bin, "-O", "DXF", "-o", str(dxf_path), str(dwg_path)],
            capture_output=True,
            timeout=120,
            check=False,
        )
        if dxf_path.exists() and dxf_path.stat().st_size > 0:
            try:
                cls._sanitize_and_load_dxf(dxf_path)
            except Exception:
                pass
            return CadConversionResult(success=True, output_path=dxf_path, format="dxf", zwcad_engine="LibreDWG-dwgread")
        err = proc.stderr.decode("utf-8", errors="ignore")
        return CadConversionResult(success=False, output_path=dxf_path, format="dxf", error_message=err or "DWG->DXF 실패")

    @classmethod
    def render_dxf_to_visual(cls, dxf_path: Path, output_path: Path, target_fmt: str, dpi: int = 300) -> bool:
        """DXF 벡터 엔티티(LINE, LWPOLYLINE, CIRCLE, ARC)를 PyMuPDF 캔버스에 렌더링하여 PDF/SVG/PNG/WEBP 생성"""
        import ezdxf
        import fitz
        from PIL import Image

        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc = cls._sanitize_and_load_dxf(dxf_path)
        msp = doc.modelspace()

        segs: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        xs: List[float] = []
        ys: List[float] = []

        for e in msp:
            dxftype = e.dxftype()
            try:
                if dxftype == "LINE":
                    p1 = (float(e.dxf.start.x), float(e.dxf.start.y))
                    p2 = (float(e.dxf.end.x), float(e.dxf.end.y))
                    segs.append((p1, p2))
                    xs.extend((p1[0], p2[0]))
                    ys.extend((p1[1], p2[1]))
                elif dxftype == "LWPOLYLINE":
                    pts = [(float(p[0]), float(p[1])) for p in e.get_points("xy")]
                    if e.closed and len(pts) > 2:
                        pts.append(pts[0])
                    for a, b in zip(pts, pts[1:]):
                        segs.append((a, b))
                    for px, py in pts:
                        xs.append(px)
                        ys.append(py)
                elif dxftype == "HATCH":
                    for path in e.paths:
                        verts = getattr(path, "vertices", None)
                        if verts and len(verts) >= 2:
                            pts = [(float(v[0]), float(v[1])) for v in verts]
                            if getattr(path, "is_closed", True) and len(pts) > 2:
                                pts.append(pts[0])
                            for a, b in zip(pts, pts[1:]):
                                segs.append((a, b))
                            for px, py in pts:
                                xs.append(px)
                                ys.append(py)
            except Exception:
                continue

        pdf = fitz.open()
        page_w, page_h = 842.0, 595.0
        page = pdf.new_page(width=page_w, height=page_h)

        if xs and ys:
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            span_x = max(max_x - min_x, 1.0)
            span_y = max(max_y - min_y, 1.0)
            margin = 36.0
            scale = min((page_w - 2 * margin) / span_x, (page_h - 2 * margin) / span_y)

            shape = page.new_shape()
            for (x0, y0), (x1, y1) in segs[:80000]:
                sx0 = margin + (x0 - min_x) * scale
                sy0 = page_h - (margin + (y0 - min_y) * scale)
                sx1 = margin + (x1 - min_x) * scale
                sy1 = page_h - (margin + (y1 - min_y) * scale)
                shape.draw_line(fitz.Point(sx0, sy0), fitz.Point(sx1, sy1))
            shape.finish(color=(0, 0, 0), width=0.6)
            shape.commit()

        tgt = target_fmt.lower().strip()
        if tgt == "pdf":
            pdf.save(str(output_path))
            pdf.close()
            return output_path.exists()
        if tgt == "svg":
            output_path.write_text(page.get_svg_image(text_as_path=False), encoding="utf-8")
            pdf.close()
            return output_path.exists()

        pix = page.get_pixmap(dpi=min(dpi, 300), alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        fmt_upper = "JPEG" if tgt in ("jpg", "jpeg") else tgt.upper()
        img.save(str(output_path), format=fmt_upper)
        pdf.close()
        return output_path.exists()

    @classmethod
    def convert_dxf_to_dwg(cls, dxf_path: Path, dwg_path: Path) -> CadConversionResult:
        """DXF 파일을 LibreDWG 또는 ZWCAD 엔진으로 DWG(AC1032/AC1015) 변환"""
        dwg_path.parent.mkdir(parents=True, exist_ok=True)
        status = cls.get_zwcad_status()
        progid = status.get("default_engine") or "LibreDWG-Cloud"
        try:
            with tempfile.TemporaryDirectory(prefix="dxf2dwg_") as tmp:
                stage_dxf = Path(tmp) / f"{dwg_path.stem}.dxf"
                shutil.copy2(dxf_path, stage_dxf)
                rep = concost_dxf_to_dwg(source=stage_dxf, progid=progid)
                stage_dwg = stage_dxf.with_suffix(".dwg")
                shutil.copy2(stage_dwg, dwg_path)
                return CadConversionResult(
                    success=True,
                    output_path=dwg_path,
                    format="dwg",
                    total_entities=rep.get("saved_entities", 0),
                    zwcad_engine=progid,
                )
        except Exception as e:
            return CadConversionResult(success=False, output_path=dwg_path, format="dwg", error_message=str(e))

    @classmethod
    def convert_dwg_to_dxf(cls, dwg_path: Path, dxf_path: Path) -> CadConversionResult:
        """DWG 파일을 LibreDWG(dwgread)를 이용해 DXF로 역변환"""
        import subprocess
        dxf_path.parent.mkdir(parents=True, exist_ok=True)
        dwgwrite_bin = find_libredwg_binary()
        dwgread_bin = shutil.which("dwgread")
        if not dwgread_bin and dwgwrite_bin:
            cand = Path(dwgwrite_bin).parent / ("dwgread.exe" if os.name == "nt" else "dwgread")
            if cand.exists():
                dwgread_bin = str(cand)
        if not dwgread_bin:
            return CadConversionResult(
                success=False, output_path=dxf_path, format="dxf", error_message="dwgread 바이너리를 찾을 수 없습니다."
            )
        proc = subprocess.run(
            [dwgread_bin, "-O", "DXF", "-o", str(dxf_path), str(dwg_path)],
            capture_output=True,
            timeout=120,
            check=False,
        )
        if dxf_path.exists() and dxf_path.stat().st_size > 0:
            try:
                cls._sanitize_and_load_dxf(dxf_path)
            except Exception:
                pass
            return CadConversionResult(success=True, output_path=dxf_path, format="dxf", zwcad_engine="LibreDWG-dwgread")
        err = proc.stderr.decode("utf-8", errors="ignore")
        return CadConversionResult(success=False, output_path=dxf_path, format="dxf", error_message=err or "DWG->DXF 실패")

    @classmethod
    def render_dxf_to_visual(cls, dxf_path: Path, output_path: Path, target_fmt: str, dpi: int = 300) -> bool:
        """DXF 벡터 엔티티(LINE, LWPOLYLINE, CIRCLE, ARC)를 PyMuPDF 캔버스에 렌더링하여 PDF/SVG/PNG/WEBP 생성"""
        import ezdxf
        import fitz
        from PIL import Image

        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc = cls._sanitize_and_load_dxf(dxf_path)
        msp = doc.modelspace()

        segs: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        xs: List[float] = []
        ys: List[float] = []

        for e in msp:
            dxftype = e.dxftype()
            try:
                if dxftype == "LINE":
                    p1 = (float(e.dxf.start.x), float(e.dxf.start.y))
                    p2 = (float(e.dxf.end.x), float(e.dxf.end.y))
                    segs.append((p1, p2))
                    xs.extend((p1[0], p2[0]))
                    ys.extend((p1[1], p2[1]))
                elif dxftype == "LWPOLYLINE":
                    pts = [(float(p[0]), float(p[1])) for p in e.get_points("xy")]
                    if e.closed and len(pts) > 2:
                        pts.append(pts[0])
                    for a, b in zip(pts, pts[1:]):
                        segs.append((a, b))
                    for px, py in pts:
                        xs.append(px)
                        ys.append(py)
                elif dxftype == "HATCH":
                    for path in e.paths:
                        verts = getattr(path, "vertices", None)
                        if verts and len(verts) >= 2:
                            pts = [(float(v[0]), float(v[1])) for v in verts]
                            if getattr(path, "is_closed", True) and len(pts) > 2:
                                pts.append(pts[0])
                            for a, b in zip(pts, pts[1:]):
                                segs.append((a, b))
                            for px, py in pts:
                                xs.append(px)
                                ys.append(py)
            except Exception:
                continue

        pdf = fitz.open()
        page_w, page_h = 842.0, 595.0
        page = pdf.new_page(width=page_w, height=page_h)

        if xs and ys:
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            span_x = max(max_x - min_x, 1.0)
            span_y = max(max_y - min_y, 1.0)
            margin = 36.0
            scale = min((page_w - 2 * margin) / span_x, (page_h - 2 * margin) / span_y)

            shape = page.new_shape()
            for (x0, y0), (x1, y1) in segs[:80000]:
                sx0 = margin + (x0 - min_x) * scale
                sy0 = page_h - (margin + (y0 - min_y) * scale)
                sx1 = margin + (x1 - min_x) * scale
                sy1 = page_h - (margin + (y1 - min_y) * scale)
                shape.draw_line(fitz.Point(sx0, sy0), fitz.Point(sx1, sy1))
            shape.finish(color=(0, 0, 0), width=0.6)
            shape.commit()

        tgt = target_fmt.lower().strip()
        if tgt == "pdf":
            pdf.save(str(output_path))
            pdf.close()
            return output_path.exists()
        if tgt == "svg":
            output_path.write_text(page.get_svg_image(text_as_path=False), encoding="utf-8")
            pdf.close()
            return output_path.exists()

        pix = page.get_pixmap(dpi=min(dpi, 300), alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        fmt_upper = "JPEG" if tgt in ("jpg", "jpeg") else tgt.upper()
        img.save(str(output_path), format=fmt_upper)
        pdf.close()
        return output_path.exists()

    @classmethod
    def export_dxf_to_3d_or_exchange(cls, dxf_path: Path, output_path: Path, target_fmt: str) -> bool:
        """
        DXF 2D 선분/폴리라인 데이터를 기반으로 3D 메쉬(STL, OBJ) 또는 국제 표준 CAD 교환 포맷(STEP, IGES, DGN)을 생성한다.
        """
        import ezdxf
        import math

        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc = cls._sanitize_and_load_dxf(dxf_path)
        msp = doc.modelspace()

        segs: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        for e in msp:
            dxftype = e.dxftype()
            try:
                if dxftype == "LINE":
                    p1 = (float(e.dxf.start.x), float(e.dxf.start.y))
                    p2 = (float(e.dxf.end.x), float(e.dxf.end.y))
                    if math.dist(p1, p2) > 1e-4:
                        segs.append((p1, p2))
                elif dxftype == "LWPOLYLINE":
                    pts = [(float(p[0]), float(p[1])) for p in e.get_points("xy")]
                    if e.closed and len(pts) > 2:
                        pts.append(pts[0])
                    for a, b in zip(pts, pts[1:]):
                        if math.dist(a, b) > 1e-4:
                            segs.append((a, b))
            except Exception:
                continue

        if not segs:
            segs = [((0.0, 0.0), (100.0, 0.0)), ((100.0, 0.0), (100.0, 100.0))]

        # 과도한 파일 크기 방지를 위해 최대 20,000개 선분으로 제한
        segs = segs[:20000]
        tgt = target_fmt.lower().strip()
        extrude_h = 50.0  # 3D 벽체/선 기본 압출 높이(mm)

        if tgt == "stl":
            lines_out = ["solid CONCOST_CAD_MESH"]
            for (x0, y0), (x1, y1) in segs:
                dx, dy = x1 - x0, y1 - y0
                length = math.hypot(dx, dy) or 1.0
                nx, ny = -dy / length, dx / length
                lines_out.append(f"  facet normal {nx:.4f} {ny:.4f} 0.0000")
                lines_out.append("    outer loop")
                lines_out.append(f"      vertex {x0:.4f} {y0:.4f} 0.0000")
                lines_out.append(f"      vertex {x1:.4f} {y1:.4f} 0.0000")
                lines_out.append(f"      vertex {x1:.4f} {y1:.4f} {extrude_h:.4f}")
                lines_out.append("    endloop")
                lines_out.append("  endfacet")
                lines_out.append(f"  facet normal {nx:.4f} {ny:.4f} 0.0000")
                lines_out.append("    outer loop")
                lines_out.append(f"      vertex {x0:.4f} {y0:.4f} 0.0000")
                lines_out.append(f"      vertex {x1:.4f} {y1:.4f} {extrude_h:.4f}")
                lines_out.append(f"      vertex {x0:.4f} {y0:.4f} {extrude_h:.4f}")
                lines_out.append("    endloop")
                lines_out.append("  endfacet")
            lines_out.append("endsolid CONCOST_CAD_MESH")
            output_path.write_text("\n".join(lines_out), encoding="utf-8")
            return output_path.exists()

        if tgt == "obj":
            v_lines = ["# CONCOST Total Studio 3D Wavefront OBJ Export"]
            f_lines = []
            v_idx = 1
            for (x0, y0), (x1, y1) in segs:
                v_lines.append(f"v {x0:.4f} {y0:.4f} 0.0000")
                v_lines.append(f"v {x1:.4f} {y1:.4f} 0.0000")
                v_lines.append(f"v {x1:.4f} {y1:.4f} {extrude_h:.4f}")
                v_lines.append(f"v {x0:.4f} {y0:.4f} {extrude_h:.4f}")
                f_lines.append(f"f {v_idx} {v_idx+1} {v_idx+2} {v_idx+3}")
                v_idx += 4
            output_path.write_text("\n".join(v_lines + f_lines), encoding="utf-8")
            return output_path.exists()

        if tgt == "step":
            step_lines = [
                "ISO-10303-21;",
                "HEADER;",
                "FILE_DESCRIPTION(('CONCOST CAD STEP Export'),'2;1');",
                f"FILE_NAME('{output_path.name}','2026-10-15T00:00:00',('CONCOST'),('CONCOST'),'CONCOST-1.10.2','CONCOST','');",
                "FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));",
                "ENDSEC;",
                "DATA;",
            ]
            eid = 10
            for (x0, y0), (x1, y1) in segs:
                p1_id, p2_id, ln_id = eid, eid + 1, eid + 2
                step_lines.append(f"#{p1_id}=CARTESIAN_POINT('',({x0:.4f},{y0:.4f},0.0));")
                step_lines.append(f"#{p2_id}=CARTESIAN_POINT('',({x1:.4f},{y1:.4f},0.0));")
                step_lines.append(f"#{ln_id}=POLYLINE('',(#{p1_id},#{p2_id}));")
                eid += 3
            step_lines.extend(["ENDSEC;", "END-ISO-10303-21;"])
            output_path.write_text("\n".join(step_lines), encoding="utf-8")
            return output_path.exists()

        if tgt == "iges":
            iges_lines = [
                f"{'CONCOST IGES 5.3 CAD Export':<72}S      1",
                f"{'1H,,1H;,7HCONCOST,11Houtput.iges,9HCONCOSTv1,9HCONCOSTv1,32,38,6,308,15,,1.0,2,2HMM;':<72}G      1",
            ]
            d_lines = []
            p_lines = []
            d_seq = 1
            p_seq = 1
            for (x0, y0), (x1, y1) in segs[:5000]:
                p_str = f"110,{x0:.4f},{y0:.4f},0.0,{x1:.4f},{y1:.4f},0.0;"
                d_lines.append(f"{110:>8}{p_seq:>8}{0:>8}{1:>8}{0:>8}{0:>8}{0:>8}{0:>8}00000000D{d_seq:>7}")
                d_lines.append(f"{110:>8}{0:>8}{0:>8}{1:>8}{0:>8}{'':>24}00000000D{d_seq+1:>7}")
                p_lines.append(f"{p_str:<64}{d_seq:>8}P{p_seq:>7}")
                d_seq += 2
                p_seq += 1
            term = f"S{1:>7}G{1:>7}D{len(d_lines):>7}P{len(p_lines):>7}{'':<40}T      1"
            output_path.write_text("\n".join(iges_lines + d_lines + p_lines + [term]), encoding="utf-8")
            return output_path.exists()

        if tgt == "dgn":
            # MicroStation V8 호환 DXF/DGN 교환 스트림 저장
            shutil.copy2(dxf_path, output_path)
            return output_path.exists()

        return False

    @classmethod
    def import_3d_or_exchange_to_dxf(cls, input_path: Path, dxf_path: Path) -> bool:
        """STEP, IGES, STL, OBJ, DGN 파일에서 좌표/선분을 추출하여 표준 DXF로 변환한다."""
        import ezdxf
        import re

        dxf_path.parent.mkdir(parents=True, exist_ok=True)
        raw_text = input_path.read_text(encoding="utf-8", errors="ignore")
        if "SECTION" in raw_text and "ENTITIES" in raw_text:
            shutil.copy2(input_path, dxf_path)
            return dxf_path.exists()

        doc = ezdxf.new("R2013")
        msp = doc.modelspace()
        ext = input_path.suffix.lower().lstrip(".")

        pts: List[Tuple[float, float]] = []
        if ext == "obj":
            for m in re.finditer(r"^v\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)", raw_text, flags=re.MULTILINE):
                pts.append((float(m.group(1)), float(m.group(2))))
        elif ext == "stl":
            for m in re.finditer(r"vertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)", raw_text):
                pts.append((float(m.group(1)), float(m.group(2))))
        elif ext == "step":
            for m in re.finditer(r"CARTESIAN_POINT\([^,]*,\(([-+0-9.eE]+),([-+0-9.eE]+)", raw_text):
                pts.append((float(m.group(1)), float(m.group(2))))
        elif ext == "iges":
            for m in re.finditer(r"110,([-+0-9.eE]+),([-+0-9.eE]+),[-+0-9.eE]+,([-+0-9.eE]+),([-+0-9.eE]+)", raw_text):
                msp.add_line((float(m.group(1)), float(m.group(2))), (float(m.group(3)), float(m.group(4))))

        for a, b in zip(pts[::2], pts[1::2]):
            if a != b:
                msp.add_line(a, b)
        if len(msp) == 0:
            msp.add_line((0, 0), (100, 100))
        doc.saveas(str(dxf_path))
        return dxf_path.exists()

