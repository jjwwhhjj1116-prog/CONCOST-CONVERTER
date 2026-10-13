"""
[검수 루프 3] 범용 이미지 엔진 검증 스크립트
다양한 포맷 상호 변환(PNG -> WEBP, JPG) 및 PDF -> 고해상도 300DPI 렌더링을 수행하고,
FeedbackAgent를 통해 무결성을 자동 검수합니다.
"""
from pathlib import Path
import sys

# 프로젝트 루트 경로 추가
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image, ImageDraw
from backend.engines.general.image_engine import ImageConversionOptions, ImageEngine
from backend.verifier.feedback_agent import FeedbackAgent


def create_sample_png(png_path: Path) -> None:
    """테스트용 RGBA 샘플 이미지 생성"""
    png_path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGBA", (400, 300), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    # 기하 도형 및 텍스트 렌더링
    draw.rectangle([20, 20, 380, 280], outline=(40, 80, 200, 255), width=3)
    draw.ellipse([100, 50, 300, 250], fill=(220, 80, 60, 200))
    img.save(str(png_path), format="PNG")


def run_image_verification() -> bool:
    """이미지 변환 엔진 검수 실행"""
    work_dir = Path("e:/■ 개발_TF팀/변환 토탈웹/temp_verify")
    work_dir.mkdir(parents=True, exist_ok=True)

    sample_png = work_dir / "sample_source.png"
    out_webp = work_dir / "sample_converted.webp"
    out_jpg = work_dir / "sample_converted.jpg"
    sample_pdf = work_dir / "sample_drawing.pdf"  # 루프 1에서 만든 PDF 활용

    # 1. 원본 PNG 생성
    create_sample_png(sample_png)

    # 2. PNG -> WEBP 변환
    ImageEngine.convert_image(
        input_path=sample_png,
        output_path=out_webp,
        options=ImageConversionOptions(target_format="WEBP", quality=95)
    )

    # 3. PNG -> JPEG 변환 (투명 알파채널 합성 포함)
    ImageEngine.convert_image(
        input_path=sample_png,
        output_path=out_jpg,
        options=ImageConversionOptions(target_format="JPEG", quality=90)
    )

    # 4. PDF -> 300DPI 고해상도 렌더링
    pdf_images = ImageEngine.convert_pdf_to_images(
        pdf_path=sample_pdf,
        output_dir=work_dir / "rendered_pages",
        options=ImageConversionOptions(target_format="PNG", dpi=300)
    )

    # 5. 피드백 에이전트를 통한 무결성/정합성 검수
    agent = FeedbackAgent(output_dir=work_dir)
    res1 = agent.verify_image(out_webp, expected_format="WEBP", min_width=300, min_height=200)
    res2 = agent.verify_image(out_jpg, expected_format="JPEG", min_width=300, min_height=200)
    
    res3_passed = True
    if pdf_images:
        res3 = agent.verify_image(pdf_images[0], expected_format="PNG", min_width=1000, min_height=700)
        res3_passed = res3.passed

    agent.print_report()
    return res1.passed and res2.passed and res3_passed


if __name__ == "__main__":
    success = run_image_verification()
    sys.exit(0 if success else 1)
