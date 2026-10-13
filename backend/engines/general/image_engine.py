"""
범용 이미지 변환 엔진 (Image Engine)
Filee 오픈소스의 핵심 변환 기능을 파이썬 표준 라이브러리(Pillow, PyMuPDF)로 구현합니다.
- 이미지 상호 변환: PNG, JPG/JPEG, WEBP, BMP, TIFF, ICO
- PDF -> 고해상도 이미지 추출 (DPI 설정 가능)
- 품질, 압축률, 리사이즈, 알파채널 합성 옵션 지원
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import fitz  # PyMuPDF
from PIL import Image


@dataclass
class ImageConversionOptions:
    """이미지 변환 옵션"""
    quality: int = 90  # 1~100 (JPEG/WEBP)
    dpi: int = 300  # PDF 변환 시 DPI
    target_format: str = "PNG"  # PNG, JPEG, WEBP, BMP, TIFF, ICO
    resize: Optional[Tuple[int, int]] = None  # (width, height)
    preserve_aspect_ratio: bool = True  # 비율 유지 여부


class ImageEngine:
    """범용 이미지 변환기"""

    @classmethod
    def convert_image(
        cls,
        input_path: Path,
        output_path: Path,
        options: Optional[ImageConversionOptions] = None,
    ) -> bool:
        """단일 이미지 파일을 지정된 타겟 포맷으로 변환합니다."""
        if options is None:
            options = ImageConversionOptions()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        target_fmt = options.target_format.upper()
        if target_fmt == "JPG":
            target_fmt = "JPEG"

        with Image.open(str(input_path)) as img:
            # 리사이즈 옵션 적용
            if options.resize:
                w, h = options.resize
                if options.preserve_aspect_ratio:
                    img.thumbnail((w, h), Image.Resampling.LANCZOS)
                else:
                    img = img.resize((w, h), Image.Resampling.LANCZOS)

            # RGBA -> RGB 변환 처리 (JPEG 등 투명 미지원 포맷 대응)
            if target_fmt in ("JPEG", "BMP") and img.mode in ("RGBA", "LA", "P"):
                background = Image.new("RGB", img.size, (255, 255, 255))
                if img.mode == "P":
                    img = img.convert("RGBA")
                background.paste(img, mask=img.split()[-1])
                img = background

            # 저장 파라미터 구성
            save_params = {}
            if target_fmt in ("JPEG", "WEBP"):
                save_params["quality"] = options.quality
            if target_fmt == "PNG":
                save_params["optimize"] = True

            img.save(str(output_path), format=target_fmt, **save_params)
        return True

    @classmethod
    def convert_pdf_to_images(
        cls,
        pdf_path: Path,
        output_dir: Path,
        options: Optional[ImageConversionOptions] = None,
        page_index: Optional[int] = None,
    ) -> list[Path]:
        """PDF 페이지들을 고해상도 이미지 파일로 렌더링 추출합니다."""
        if options is None:
            options = ImageConversionOptions()

        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[Path] = []
        target_fmt = options.target_format.lower()
        if target_fmt == "jpeg":
            target_fmt = "jpg"

        # DPI 기반 확대 비율 계산 (기본 72 DPI 기준)
        zoom = options.dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        with fitz.open(pdf_path) as doc:
            pages_to_convert = [page_index] if page_index is not None else range(len(doc))
            for pno in pages_to_convert:
                if 0 <= pno < len(doc):
                    page = doc[pno]
                    pix = page.get_pixmap(matrix=matrix, alpha=False)
                    out_name = f"{pdf_path.stem}_p{pno + 1}.{target_fmt}"
                    out_file = output_dir / out_name
                    pix.save(str(out_file))
                    results.append(out_file)

        return results
