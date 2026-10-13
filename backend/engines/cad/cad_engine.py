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
from backend.engines.cad.concost_dwg import convert_dwg as concost_dxf_to_dwg, installed_zwcad
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

    @classmethod
    def get_zwcad_status(cls) -> Dict[str, Any]:
        """로컬 시스템의 ZWCAD 설치 및 COM API 연동 상태 조회"""
        try:
            versions = installed_zwcad()
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
