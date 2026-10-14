# REA (Reverse Engineer Anything) - KnifeLemon/Filee 복제 및 아키텍처 이식 보고서

- **분석 대상**: `https://github.com/KnifeLemon/Filee` (`e:/■ 개발_TF팀/Filee`)
- **역공학 도구**: `morluto/rea` (`e:/■ 개발_TF팀/rea` 스킬/에이전트)
- **전체 C# 소스 파일 수**: 341개 (`Filee.Core`: 25개, `Filee.Engines`: 138개)

## 1. Filee 핵심 엔진 구조 및 CONCOST 이식 매핑

| 영역 | Filee 원본 (`src/Filee.Engines`) | CONCOST 이식 모듈 | 비고 |
| :--- | :--- | :--- | :--- |
| **CAD 도면 (DXF/DWG)** | `Cad/CadConverter.cs` (ACadSharp) | `backend/engines/cad/concost_converter.py` + `concost_dwg.py` | **사용자 전용 CONCOST-Converter-0.2.2 + LibreDWG/ZWCAD 유지 (더 정밀한 베지어 분할·레이어 분리)** |
| **문서 통합 리더** | `Hwp/Hwpx/DocumentReaders.cs` | `FileeDocumentReaders` (`filee_universal.py`) | PDF, DOCX, HWPX, HWP(OLE2), XLSX, ODS, CSV, TSV, HTML, RTF, ODT, EPUB, FB2, PPTX 통합 파싱 |
| **HWPX 작성기** | `Hwp/Hwpx/HwpxWriter.cs` | `FileeHwpxWriter` (`filee_universal.py`) | 한컴오피스 없이 순수 OWPML 표준 `.hwpx` 패키지 직접 생성 |
| **DOCX 작성기** | `Hwp/Hwpx/Docx/DocxWriter.cs` | `FileeDocxWriter` (`filee_universal.py`) | MS Word 없이 순수 WordprocessingML `.docx` 패키지 직접 생성 |
| **스프레드시트** | `Office/SpreadsheetConverter.cs` | `FileeSpreadsheetConverter` + `TableEngine` | XLSX, XLS, ODS, CSV, TSV, HTML 양방향 및 PDF 격자 표 복원 |
| **전자책 (E-Books)** | `Ebooks/EbookConverter.cs` | `FileeEbookConverter` (`filee_universal.py`) | EPUB 3, FB2, AZW3, MOBI, CBZ 양방향 변환 |
| **압축 (Archives)** | `Archives/SevenZipConverter.cs` | `FileeArchiveConverter` (`filee_universal.py`) | ZIP, 7Z, TAR, GZ, BZ2 패킹 및 아카이브 상호 변환 |
| **폰트 (Fonts)** | `Fonts/FontConverter.cs` | `FileeFontConverter` (`filee_universal.py`) | `fontTools` 기반 TTF, OTF, WOFF, WOFF2 상호 변환 |
| **다단계 라우터** | `Filee.Core/Conversion/RoutePlanner.cs` | `FileeUniversalRouter` (`filee_universal.py`) | 다익스트라 기반 다단계 변환 (`DOCX -> PDF -> PNG` 등) |
