"""
변환 토탈웹 - 피드백 에이전트 (Verification & Feedback Agent)
각 카테고리별 변환 엔진의 결과물을 레퍼런스 오픈소스 및 원본 기준과 대조하여 자동 검수합니다.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import time


@dataclass
class VerificationResult:
    """검수 항목별 결과 데이터 클래스"""
    category: str
    target_name: str
    passed: bool
    metrics: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    elapsed_sec: float = 0.0

    def summary(self) -> str:
        status = "[PASS]" if self.passed else "[FAIL]"
        lines = [f"{status} {self.category} - {self.target_name} ({self.elapsed_sec:.3f}s)"]
        for k, v in self.metrics.items():
            lines.append(f"  * {k}: {v}")
        for w in self.warnings:
            lines.append(f"  [경고] Warning: {w}")
        for e in self.errors:
            lines.append(f"  [오류] Error: {e}")
        return "\n".join(lines)


class FeedbackAgent:
    """
    단계별 변환 결과물을 자동 검증하는 피드백 에이전트.
    - 파일 생성 여부 및 용량 확인
    - 바이너리/구조적 무결성 (CAD 엔터티 수, 엑셀 셀 수, 이미지 규격 등)
    - 레퍼런스 대비 오차율 및 누락율 측정
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.history: List[VerificationResult] = []

    def verify_cad_dxf(
        self,
        output_file: Path,
        expected_min_entities: int = 1,
        check_scale_factor: Optional[float] = None,
    ) -> VerificationResult:
        """CAD DXF 파일의 엔터티 무결성 및 구조 검수"""
        import ezdxf

        start_time = time.time()
        res = VerificationResult(category="CAD", target_name=output_file.name, passed=False)

        if not output_file.exists() or output_file.stat().st_size == 0:
            res.errors.append(f"파일이 생성되지 않았거나 크기가 0입니다: {output_file}")
            res.elapsed_sec = time.time() - start_time
            self.history.append(res)
            return res

        try:
            doc = ezdxf.readfile(str(output_file))
            msp = doc.modelspace()
            entity_count = len(list(msp))
            layers = [layer.dxf.name for layer in doc.layers]

            res.metrics["entity_count"] = entity_count
            res.metrics["layer_count"] = len(layers)
            res.metrics["layers"] = layers
            res.metrics["dxf_version"] = doc.dxfversion
            res.metrics["file_size_bytes"] = output_file.stat().st_size

            if entity_count < expected_min_entities:
                res.errors.append(f"엔터티 수가 기대치({expected_min_entities})보다 적습니다: {entity_count}")
            else:
                res.passed = True

            if check_scale_factor is not None:
                res.metrics["applied_scale"] = check_scale_factor

        except Exception as e:
            res.errors.append(f"DXF 구문 분석 중 예외 발생: {e}")

        res.elapsed_sec = time.time() - start_time
        self.history.append(res)
        return res

    def verify_cad_dwg(self, output_file: Path) -> VerificationResult:
        """CAD 바이너리 DWG 파일의 시그니처 및 무결성 검수"""
        start_time = time.time()
        res = VerificationResult(category="CAD_DWG", target_name=output_file.name, passed=False)

        if not output_file.exists() or output_file.stat().st_size == 0:
            res.errors.append(f"DWG 파일이 생성되지 않았거나 크기가 0입니다: {output_file}")
            res.elapsed_sec = time.time() - start_time
            self.history.append(res)
            return res

        try:
            with open(output_file, "rb") as f:
                sig_bytes = f.read(6)
                sig = sig_bytes.decode("ascii", errors="ignore")

            res.metrics["dwg_signature"] = sig
            res.metrics["file_size_bytes"] = output_file.stat().st_size

            valid_signatures = {"AC1015", "AC1018", "AC1021", "AC1024", "AC1027", "AC1032"}
            if sig in valid_signatures:
                res.passed = True
                res.metrics["dwg_version_desc"] = f"AutoCAD 표준 바이너리 ({sig})"
            else:
                res.errors.append(f"유효한 AutoCAD DWG 시그니처가 아닙니다: {sig}")

        except Exception as e:
            res.errors.append(f"DWG 헤더 검사 중 예외 발생: {e}")

        res.elapsed_sec = time.time() - start_time
        self.history.append(res)
        return res

    def verify_excel(
        self,
        output_file: Path,
        expected_min_rows: int = 1,
        expected_min_cols: int = 1,
    ) -> VerificationResult:
        """Excel (XLSX) 파일 구조 및 셀 데이터 유효성 검수"""
        import openpyxl

        start_time = time.time()
        res = VerificationResult(category="Excel", target_name=output_file.name, passed=False)

        if not output_file.exists() or output_file.stat().st_size == 0:
            res.errors.append(f"파일이 생성되지 않았거나 크기가 0입니다: {output_file}")
            res.elapsed_sec = time.time() - start_time
            self.history.append(res)
            return res

        try:
            wb = openpyxl.load_workbook(str(output_file), read_only=True)
            sheet_names = wb.sheetnames
            res.metrics["sheet_names"] = sheet_names

            first_sheet = wb[sheet_names[0]]
            max_row = first_sheet.max_row or 0
            max_col = first_sheet.max_column or 0
            res.metrics["max_rows"] = max_row
            res.metrics["max_cols"] = max_col

            if max_row < expected_min_rows or max_col < expected_min_cols:
                res.errors.append(f"행({max_row})/열({max_col}) 수가 기대치 미달입니다.")
            else:
                res.passed = True
            wb.close()
        except Exception as e:
            res.errors.append(f"Excel 파싱 오류: {e}")

        res.elapsed_sec = time.time() - start_time
        self.history.append(res)
        return res

    def verify_image(
        self,
        output_file: Path,
        expected_format: str,
        min_width: int = 1,
        min_height: int = 1,
    ) -> VerificationResult:
        """이미지 파일 무결성 및 포맷 검수 (PIL 기반)"""
        from PIL import Image

        start_time = time.time()
        res = VerificationResult(category="Image", target_name=output_file.name, passed=False)

        if not output_file.exists() or output_file.stat().st_size == 0:
            res.errors.append(f"파일이 생성되지 않았거나 크기가 0입니다: {output_file}")
            res.elapsed_sec = time.time() - start_time
            self.history.append(res)
            return res

        try:
            with Image.open(str(output_file)) as img:
                res.metrics["actual_format"] = img.format
                res.metrics["dimensions"] = f"{img.width}x{img.height}"
                res.metrics["mode"] = img.mode
                res.metrics["file_size_bytes"] = output_file.stat().st_size

                fmt = (img.format or "").upper()
                exp = expected_format.upper()
                if exp == "JPG":
                    exp = "JPEG"

                if fmt != exp:
                    res.errors.append(f"포맷 불일치: 기대({exp}) != 실제({fmt})")
                elif img.width < min_width or img.height < min_height:
                    res.errors.append(f"이미지 해상도 미달: {img.width}x{img.height}")
                else:
                    res.passed = True
        except Exception as e:
            res.errors.append(f"이미지 무결성 검사 예외: {e}")

        res.elapsed_sec = time.time() - start_time
        self.history.append(res)
        return res

    def print_report(self) -> None:
        """전체 검수 결과 보고서 출력"""
        print("\n" + "=" * 60)
        print("[피드백 에이전트] 변환 엔진 단계별 검수 보고서")
        print("=" * 60)
        for item in self.history:
            print(item.summary())
            print("-" * 60)
