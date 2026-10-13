"""
압축 및 아카이브 엔진 (Archive Engine)
다중 파일 및 변환 결과물을 Deflate 알고리즘 기반 무손실 ZIP으로 패킹합니다. (Filee "One ZIP" 대응)
"""
from pathlib import Path
from typing import List
import zipfile


class ArchiveEngine:
    """압축 변환기"""

    @classmethod
    def create_zip(cls, files: List[Path], output_zip: Path) -> bool:
        """파일 리스트를 단일 ZIP 파일로 압축 생성"""
        output_zip.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                if f.exists():
                    zf.write(f, arcname=f.name)
        return output_zip.exists() and output_zip.stat().st_size > 0
