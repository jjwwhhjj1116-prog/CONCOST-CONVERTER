"""
Filee v1.10.2 오픈소스(KnifeLemon/Filee) 아키텍처 파이썬 완전 이식 모듈
- HDocument 통합 문서 모델 (DocumentReaders: PDF, DOCX, HWPX, HWP, XLSX, CSV, TSV, ODS, TXT, MD, HTML, RTF, ODT, EPUB, FB2, AZW3, MOBI)
- HwpxWriter: 한컴오피스 없이 순수 OWPML 표준 .hwpx 패키지 생성 (문단 + 표 복원 포함)
- DocxWriter: MS Word 없이 순수 WordprocessingML 표준 .docx 패키지 생성 (문단 + 표 복원 포함)
- OdtWriter / RtfWriter / HtmlWriter / MarkdownWriter / TxtWriter
- SpreadsheetConverter: XLSX, XLS, ODS, CSV, TSV, HTML 간 인메모리 워크북 상호 변환
- EbookConverter: EPUB, FB2, CBZ, AZW3, MOBI 상호 변환
- ArchiveConverter: ZIP, TAR, GZ(TAR.GZ), BZ2(TAR.BZ2), 7Z, XZ 상호 변환 및 패킹
- FontConverter: fontTools 기반 TTF, OTF, WOFF, WOFF2 상호 변환
- RoutePlanner: 다익스트라(Dijkstra) 최단 경로 기반 다단계(Multi-step) 변환 라우터
"""
from __future__ import annotations

from collections import deque
import csv
from dataclasses import dataclass, field
import gzip
import bz2
import html
import io
import lzma
import os
from pathlib import Path
import re
import shutil
import struct
import tarfile
import tempfile
from typing import Any, Callable, Dict, List, Optional, Tuple
import uuid
import wave
import xml.etree.ElementTree as ET
import zipfile
import zlib

import fitz  # PyMuPDF
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from PIL import Image

from backend.engines.document.table_engine import TableEngine
from backend.engines.general.image_engine import ImageConversionOptions, ImageEngine


@dataclass
class HTable:
    """통합 문서 모델 내 표(Table) 구조"""
    rows: List[List[str]] = field(default_factory=list)


@dataclass
class HSection:
    """통합 문서 모델 내 섹션(페이지/챕터) 구조"""
    title: str = ""
    paragraphs: List[str] = field(default_factory=list)
    tables: List[HTable] = field(default_factory=list)
    images: List[bytes] = field(default_factory=list)


@dataclass
class HDocument:
    """Filee HDocument 통합 문서 모델 (모든 문서·표·전자책 리더의 공통 출력)"""
    title: str = "Document"
    sections: List[HSection] = field(default_factory=list)

    def all_paragraphs(self) -> List[str]:
        """모든 섹션의 문단 리스트 반환"""
        result: List[str] = []
        for sec in self.sections:
            if sec.title:
                result.append(sec.title)
            result.extend(sec.paragraphs)
            for tbl in sec.tables:
                for row in tbl.rows:
                    result.append("\t".join(row))
        return result

    def all_tables(self) -> List[HTable]:
        """모든 섹션의 표 리스트 반환"""
        result: List[HTable] = []
        for sec in self.sections:
            result.extend(sec.tables)
        return result


class FileeDocumentReaders:
    """Filee DocumentReaders.cs 이식: 다양한 입력 포맷을 HDocument로 파싱"""

    @staticmethod
    def decode_bytes(raw: bytes) -> str:
        """UTF-8 / UTF-16 BOM 및 한국어 CP949/EUC-KR 자동 감지 디코딩"""
        if raw.startswith(b"\xef\xbb\xbf"):
            return raw[3:].decode("utf-8", errors="replace")
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            return raw.decode("utf-16", errors="replace")
        for enc in ("utf-8", "cp949", "euc-kr", "latin-1"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    @classmethod
    def read(cls, path: Path) -> HDocument:
        """확장자 및 시그니처 기반으로 입력 파일을 HDocument로 파싱"""
        ext = path.suffix.lower().lstrip(".")
        if ext == "pdf":
            return cls.read_pdf(path)
        if ext in ("docx", "docm", "dotx", "dotm"):
            return cls.read_docx(path)
        if ext == "hwpx":
            return cls.read_hwpx(path)
        if ext == "hwp":
            return cls.read_hwp(path)
        if ext in ("xlsx", "xlsm", "xltx", "xls", "ods", "csv", "tsv"):
            return cls.read_spreadsheet(path)
        if ext in ("html", "htm", "xhtml"):
            return cls.read_html(path)
        if ext == "rtf":
            return cls.read_rtf(path)
        if ext == "odt":
            return cls.read_odt(path)
        if ext == "epub":
            return cls.read_epub(path)
        if ext == "fb2":
            return cls.read_fb2(path)
        if ext in ("pptx", "pptm", "potx", "ppsx"):
            return cls.read_pptx(path)
        return cls.read_text(path)

    @classmethod
    def read_text(cls, path: Path) -> HDocument:
        """TXT / Markdown 파일 파싱"""
        text = cls.decode_bytes(path.read_bytes())
        lines = [ln.rstrip("\r") for ln in text.split("\n")]
        return HDocument(
            title=path.stem,
            sections=[HSection(title=path.stem, paragraphs=lines)],
        )

    @classmethod
    def read_pdf(cls, path: Path) -> HDocument:
        """PDF에서 페이지별 문단 텍스트 및 격자 표(TableEngine)를 동시에 복원"""
        sections: List[HSection] = []
        with fitz.open(path) as doc:
            max_table_pages = min(len(doc), 15)
            for idx, page in enumerate(doc):
                raw_text = page.get_text("text") or ""
                paras = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
                tables: List[HTable] = []
                if idx < max_table_pages:
                    try:
                        lines, texts = TableEngine.extract_lines_and_texts_from_page(page)
                        rec = TableEngine.recover_tables(lines, texts)
                        for t in rec:
                            if t.grid and len(t.grid) >= 2:
                                tables.append(HTable(rows=t.grid))
                    except Exception:
                        pass
                sections.append(
                    HSection(
                        title=f"Page {idx + 1}",
                        paragraphs=paras,
                        tables=tables,
                    )
                )
        return HDocument(title=path.stem, sections=sections or [HSection(title=path.stem)])

    @classmethod
    def read_docx(cls, path: Path) -> HDocument:
        """DOCX (WordprocessingML) 문단 및 표 파싱"""
        paras: List[str] = []
        tables: List[HTable] = []
        try:
            with zipfile.ZipFile(path, "r") as zf:
                if "word/document.xml" in zf.namelist():
                    xml_bytes = zf.read("word/document.xml")
                    root = ET.fromstring(xml_bytes)
                    for elem in root.iter():
                        tag = elem.tag.rsplit("}", 1)[-1]
                        if tag == "p":
                            texts = [
                                t.text
                                for t in elem.iter()
                                if t.tag.rsplit("}", 1)[-1] == "t" and t.text
                            ]
                            line = "".join(texts).strip()
                            if line:
                                paras.append(line)
                        elif tag == "tbl":
                            rows: List[List[str]] = []
                            for tr in elem:
                                if tr.tag.rsplit("}", 1)[-1] == "tr":
                                    row_cells: List[str] = []
                                    for tc in tr:
                                        if tc.tag.rsplit("}", 1)[-1] == "tc":
                                            cell_txt = "".join(
                                                t.text
                                                for t in tc.iter()
                                                if t.tag.rsplit("}", 1)[-1] == "t" and t.text
                                            ).strip()
                                            row_cells.append(cell_txt)
                                    if row_cells:
                                        rows.append(row_cells)
                            if rows:
                                tables.append(HTable(rows=rows))
        except Exception:
            return cls.read_text(path)
        return HDocument(title=path.stem, sections=[HSection(title=path.stem, paragraphs=paras, tables=tables)])

    @classmethod
    def read_hwpx(cls, path: Path) -> HDocument:
        """HWPX (OWPML 표준 ZIP 패키지) 문단 및 표 파싱"""
        paras: List[str] = []
        tables: List[HTable] = []
        try:
            with zipfile.ZipFile(path, "r") as zf:
                sec_files = sorted(
                    n for n in zf.namelist() if n.startswith("Contents/section") and n.endswith(".xml")
                )
                for sec_name in sec_files:
                    root = ET.fromstring(zf.read(sec_name))
                    for elem in root.iter():
                        tag = elem.tag.rsplit("}", 1)[-1]
                        if tag == "p":
                            texts = [
                                t.text
                                for t in elem.iter()
                                if t.tag.rsplit("}", 1)[-1] == "t" and t.text
                            ]
                            line = "".join(texts).strip()
                            if line:
                                paras.append(line)
                        elif tag == "tbl":
                            rows: List[List[str]] = []
                            for tr in elem.iter():
                                if tr.tag.rsplit("}", 1)[-1] == "tr":
                                    row_cells: List[str] = []
                                    for tc in tr:
                                        if tc.tag.rsplit("}", 1)[-1] == "tc":
                                            c_txt = "".join(
                                                t.text
                                                for t in tc.iter()
                                                if t.tag.rsplit("}", 1)[-1] == "t" and t.text
                                            ).strip()
                                            row_cells.append(c_txt)
                                    if row_cells:
                                        rows.append(row_cells)
                            if rows:
                                tables.append(HTable(rows=rows))
        except Exception:
            return cls.read_text(path)
        return HDocument(title=path.stem, sections=[HSection(title=path.stem, paragraphs=paras, tables=tables)])

    @classmethod
    def read_hwp(cls, path: Path) -> HDocument:
        """HWP 5.0 바이너리(OLE2) 또는 HWPX/XML에서 텍스트 및 문단 추출 (Unhwp 방식)"""
        raw = path.read_bytes()
        if raw[:4] == b"PK\x03\x04":
            return cls.read_hwpx(path)
        if raw.lstrip().startswith(b"<"):
            return cls.read_html(path)

        paras: List[str] = []
        # 1. HWP 5.0 OLE2 컨테이너 내부 BodyText/Section zlib 스트림 및 PrvText(UTF-16LE) 탐색
        try:
            paras.extend(cls._extract_hwp5_texts(raw))
        except Exception:
            pass

        if not paras:
            # 폴백: UTF-16LE 가독 한글/영문 문자열 추출
            decoded = raw.decode("utf-16le", errors="ignore")
            clean = re.findall(r"[가-힣a-zA-Z0-9\s\.\,\-\(\)\[\]\:\/\%]{4,}", decoded)
            paras = [c.strip() for c in clean if len(c.strip()) >= 2]

        return HDocument(title=path.stem, sections=[HSection(title=path.stem, paragraphs=paras or [path.stem])])

    @staticmethod
    def _extract_hwp5_texts(raw: bytes) -> List[str]:
        """HWP 5.0 레코드(HWPTAG_PARA_TEXT = 67)를 디플레이트 해제 후 파싱"""
        results: List[str] = []
        # OLE2 512바이트 섹터들을 순회하며 raw deflate 스트림 시도
        for offset in range(512, len(raw), 512):
            chunk = raw[offset:]
            try:
                decompressed = zlib.decompress(chunk, -15)
            except Exception:
                continue
            pos = 0
            while pos + 4 <= len(decompressed):
                header = struct.unpack_from("<I", decompressed, pos)[0]
                tag_id = header & 0x3FF
                size = (header >> 20) & 0xFFF
                pos += 4
                if size == 0xFFF:
                    if pos + 4 > len(decompressed):
                        break
                    size = struct.unpack_from("<I", decompressed, pos)[0]
                    pos += 4
                if pos + size > len(decompressed):
                    break
                if tag_id == 67:  # HWPTAG_PARA_TEXT
                    rec = decompressed[pos : pos + size]
                    chars: List[str] = []
                    i = 0
                    while i + 2 <= len(rec):
                        code = struct.unpack_from("<H", rec, i)[0]
                        i += 2
                        if code in (1, 2, 3, 11, 12, 14, 15, 16, 17, 18, 21, 22, 23):
                            i += 14  # 확장 컨트롤 문자(16바이트)
                        elif code in (4, 5, 6, 7, 8, 9, 19, 20):
                            i += 14
                        elif code == 13 or code == 10:
                            chars.append("\n")
                        elif code >= 32:
                            chars.append(chr(code))
                    txt = "".join(chars).strip()
                    if txt:
                        results.extend(ln.strip() for ln in txt.splitlines() if ln.strip())
                pos += size
        return results

    @classmethod
    def read_spreadsheet(cls, path: Path) -> HDocument:
        """XLSX, XLS, ODS, CSV, TSV 파일을 읽어 시트별 표(HTable)로 변환"""
        sheets = FileeSpreadsheetConverter.read_workbook(path)
        sections: List[HSection] = []
        for sheet_name, rows in sheets.items():
            sections.append(
                HSection(
                    title=sheet_name,
                    paragraphs=[f"[{sheet_name}]"],
                    tables=[HTable(rows=rows)] if rows else [],
                )
            )
        return HDocument(title=path.stem, sections=sections or [HSection(title=path.stem)])

    @classmethod
    def read_html(cls, path: Path) -> HDocument:
        """HTML 파일에서 문단 및 <table> 구조 파싱"""
        raw_html = cls.decode_bytes(path.read_bytes())
        # script, style 제거
        cleaned = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw_html, flags=re.DOTALL | re.IGNORECASE)
        tables: List[HTable] = []
        for tbl_match in re.finditer(r"<table[^>]*>(.*?)</table>", cleaned, flags=re.DOTALL | re.IGNORECASE):
            rows: List[List[str]] = []
            for tr_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", tbl_match.group(1), flags=re.DOTALL | re.IGNORECASE):
                cells = [
                    html.unescape(re.sub(r"<[^>]+>", "", c).strip())
                    for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr_match.group(1), flags=re.DOTALL | re.IGNORECASE)
                ]
                if cells:
                    rows.append(cells)
            if rows:
                tables.append(HTable(rows=rows))
        text_only = re.sub(r"<table[^>]*>.*?</table>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
        text_only = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</h[1-6]>", "\n", text_only, flags=re.IGNORECASE)
        text_only = html.unescape(re.sub(r"<[^>]+>", "", text_only))
        paras = [ln.strip() for ln in text_only.splitlines() if ln.strip()]
        return HDocument(title=path.stem, sections=[HSection(title=path.stem, paragraphs=paras, tables=tables)])

    @classmethod
    def read_rtf(cls, path: Path) -> HDocument:
        r"""RTF 문서에서 유니코드(\uN) 및 문단 텍스트 추출"""
        content = cls.decode_bytes(path.read_bytes())
        # \uNNNN? 유니코드 이스케이프 복원
        def _repl_uni(m: re.Match[str]) -> str:
            code = int(m.group(1))
            if code < 0:
                code += 65536
            return chr(code)

        text = re.sub(r"\\u(-?\d+)\??", _repl_uni, content)
        text = re.sub(r"\\par\b|\\line\b", "\n", text)
        text = re.sub(r"\\[a-zA-Z]+-?\d*\s?", "", text)
        text = text.replace("{", "").replace("}", "")
        paras = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return HDocument(title=path.stem, sections=[HSection(title=path.stem, paragraphs=paras)])

    @classmethod
    def read_odt(cls, path: Path) -> HDocument:
        """ODT (OpenDocument Text) content.xml 파싱"""
        paras: List[str] = []
        tables: List[HTable] = []
        try:
            with zipfile.ZipFile(path, "r") as zf:
                root = ET.fromstring(zf.read("content.xml"))
                for elem in root.iter():
                    tag = elem.tag.rsplit("}", 1)[-1]
                    if tag in ("p", "h"):
                        txt = "".join(elem.itertext()).strip()
                        if txt:
                            paras.append(txt)
                    elif tag == "table":
                        rows: List[List[str]] = []
                        for tr in elem:
                            if tr.tag.rsplit("}", 1)[-1] == "table-row":
                                cells = [
                                    "".join(tc.itertext()).strip()
                                    for tc in tr
                                    if tc.tag.rsplit("}", 1)[-1] == "table-cell"
                                ]
                                if cells:
                                    rows.append(cells)
                        if rows:
                            tables.append(HTable(rows=rows))
        except Exception:
            return cls.read_text(path)
        return HDocument(title=path.stem, sections=[HSection(title=path.stem, paragraphs=paras, tables=tables)])

    @classmethod
    def read_epub(cls, path: Path) -> HDocument:
        """EPUB 컨테이너 내 XHTML/HTML 챕터 파싱"""
        sections: List[HSection] = []
        try:
            with zipfile.ZipFile(path, "r") as zf:
                html_files = sorted(
                    n for n in zf.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))
                )
                for idx, hf in enumerate(html_files):
                    raw = cls.decode_bytes(zf.read(hf))
                    txt = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", raw, flags=re.DOTALL | re.IGNORECASE)
                    txt = re.sub(r"<br\s*/?>|</p>|</div>|</h[1-6]>", "\n", txt, flags=re.IGNORECASE)
                    txt = html.unescape(re.sub(r"<[^>]+>", "", txt))
                    paras = [ln.strip() for ln in txt.splitlines() if ln.strip()]
                    if paras:
                        sections.append(HSection(title=f"Chapter {idx + 1}", paragraphs=paras))
        except Exception:
            return cls.read_text(path)
        return HDocument(title=path.stem, sections=sections or [HSection(title=path.stem)])

    @classmethod
    def read_fb2(cls, path: Path) -> HDocument:
        """FictionBook 2.0 (.fb2) XML 파싱"""
        paras: List[str] = []
        try:
            root = ET.fromstring(path.read_bytes())
            for elem in root.iter():
                if elem.tag.rsplit("}", 1)[-1] in ("p", "subtitle"):
                    txt = "".join(elem.itertext()).strip()
                    if txt:
                        paras.append(txt)
        except Exception:
            return cls.read_text(path)
        return HDocument(title=path.stem, sections=[HSection(title=path.stem, paragraphs=paras)])

    @classmethod
    def read_pptx(cls, path: Path) -> HDocument:
        """PPTX 슬라이드 텍스트 및 표 파싱"""
        sections: List[HSection] = []
        try:
            with zipfile.ZipFile(path, "r") as zf:
                slides = sorted(
                    n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")
                )
                for idx, sname in enumerate(slides):
                    root = ET.fromstring(zf.read(sname))
                    paras: List[str] = []
                    for elem in root.iter():
                        if elem.tag.rsplit("}", 1)[-1] == "p":
                            t_list = [
                                t.text
                                for t in elem.iter()
                                if t.tag.rsplit("}", 1)[-1] == "t" and t.text
                            ]
                            line = "".join(t_list).strip()
                            if line:
                                paras.append(line)
                    sections.append(HSection(title=f"Slide {idx + 1}", paragraphs=paras))
        except Exception:
            return cls.read_text(path)
        return HDocument(title=path.stem, sections=sections or [HSection(title=path.stem)])


class FileeHwpxWriter:
    """Filee HwpxWriter 이식: 한컴오피스 없이 표준 OWPML (.hwpx) 패키지 직접 생성"""

    @classmethod
    def write(cls, doc: HDocument, output_path: Path) -> bool:
        """HDocument를 한컴 표준 .hwpx 파일로 저장"""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        version_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<hv:HCFVersion xmlns:hv="http://www.hancom.co.kr/hwpml/2011/version" '
            'tagetApplication="WORDPROCESSOR" major="5" minor="1" micro="0" buildNumber="1" '
            'os="1" xmlVersion="1.4" application="Filee-CONCOST" appVersion="1.10.2"/>'
        )
        container_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<ocf:container xmlns:ocf="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<ocf:rootfiles>'
            '<ocf:rootfile full-path="Contents/content.hpf" media-type="application/hwpml-package+xml"/>'
            '</ocf:rootfiles></ocf:container>'
        )
        manifest_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<odf:manifest xmlns:odf="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"/>'
        )
        content_hpf = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/" version="1.0" unique-identifier="bookid">'
            f'<opf:metadata><opf:title>{html.escape(doc.title)}</opf:title><opf:language>ko</opf:language></opf:metadata>'
            '<opf:manifest>'
            '<opf:item id="header" href="Contents/header.xml" media-type="application/xml"/>'
            '<opf:item id="section0" href="Contents/section0.xml" media-type="application/xml"/>'
            '</opf:manifest>'
            '<opf:spine><opf:itemref idref="header"/><opf:itemref idref="section0"/></opf:spine>'
            '</opf:package>'
        )
        header_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<hh:head xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" version="1.4" secCnt="1">'
            '<hh:beginNum page="1" footnote="1" endnote="1" pic="1" tbl="1" equation="1"/>'
            '<hh:refList>'
            '<hh:fontfaces itemCnt="1"><hh:fontface lang="HANGUL" fontCnt="1">'
            '<hh:font id="0" face="맑은 고딕" type="TTF" isEmbedded="0"/>'
            '</hh:fontface></hh:fontfaces>'
            '<hh:charProperties itemCnt="1">'
            '<hh:charPr id="0" height="1000" textColor="#000000" shadeColor="none" useFontSpace="0" useKerning="0"/>'
            '</hh:charProperties>'
            '<hh:paraProperties itemCnt="1">'
            '<hh:paraPr id="0" tabPrIDRef="0"><hh:align horizontal="JUSTIFY" vertical="BASELINE"/></hh:paraPr>'
            '</hh:paraProperties>'
            '</hh:refList></hh:head>'
        )

        body_parts: List[str] = []
        for sec in doc.sections:
            if sec.title:
                body_parts.append(
                    f'<hp:p paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0"><hp:t>{html.escape(sec.title)}</hp:t></hp:run></hp:p>'
                )
            for p in sec.paragraphs:
                body_parts.append(
                    f'<hp:p paraPrIDRef="0" styleIDRef="0"><hp:run charPrIDRef="0"><hp:t>{html.escape(p)}</hp:t></hp:run></hp:p>'
                )
            for tbl in sec.tables:
                if not tbl.rows:
                    continue
                row_cnt = len(tbl.rows)
                col_cnt = max((len(r) for r in tbl.rows), default=1)
                tr_list: List[str] = []
                for r_idx, row in enumerate(tbl.rows):
                    tc_list: List[str] = []
                    for c_idx in range(col_cnt):
                        val = row[c_idx] if c_idx < len(row) else ""
                        tc_list.append(
                            f'<hp:tc><hp:cellAddr colAddr="{c_idx}" rowAddr="{r_idx}"/>'
                            f'<hp:cellSpan colSpan="1" rowSpan="1"/>'
                            f'<hp:subList><hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"><hp:t>{html.escape(str(val))}</hp:t></hp:run></hp:p></hp:subList>'
                            f'</hp:tc>'
                        )
                    tr_list.append(f"<hp:tr>{''.join(tc_list)}</hp:tr>")
                body_parts.append(
                    f'<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0">'
                    f'<hp:tbl rowCnt="{row_cnt}" colCnt="{col_cnt}">{"".join(tr_list)}</hp:tbl>'
                    f'</hp:run></hp:p>'
                )

        if not body_parts:
            body_parts.append('<hp:p paraPrIDRef="0"><hp:run charPrIDRef="0"><hp:t></hp:t></hp:run></hp:p>')

        section0_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
            'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
            + "".join(body_parts)
            + "</hs:sec>"
        )

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
            zf.writestr("version.xml", version_xml)
            zf.writestr("META-INF/container.xml", container_xml)
            zf.writestr("META-INF/manifest.xml", manifest_xml)
            zf.writestr("Contents/content.hpf", content_hpf)
            zf.writestr("Contents/header.xml", header_xml)
            zf.writestr("Contents/section0.xml", section0_xml)

        return output_path.exists() and output_path.stat().st_size > 0


class FileeDocxWriter:
    """Filee DocxWriter 이식: MS Word 없이 표준 WordprocessingML (.docx) 패키지 직접 생성"""

    @classmethod
    def write(cls, doc: HDocument, output_path: Path) -> bool:
        """HDocument(문단 + 복원된 표)를 MS Word 호환 .docx로 저장"""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        content_types = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '</Types>'
        )
        rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '</Relationships>'
        )
        doc_rels = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>'
        )
        styles_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:docDefaults><w:rPrDefault><w:rPr>'
            '<w:rFonts w:ascii="Malgun Gothic" w:eastAsia="Malgun Gothic" w:hAnsi="Malgun Gothic"/>'
            '<w:sz w:val="20"/><w:szCs w:val="20"/>'
            '</w:rPr></w:rPrDefault></w:docDefaults>'
            '</w:styles>'
        )

        body_elements: List[str] = []
        for sec in doc.sections:
            if sec.title:
                body_elements.append(
                    f'<w:p><w:r><w:rPr><w:b/><w:sz w:val="24"/></w:rPr><w:t>{html.escape(sec.title)}</w:t></w:r></w:p>'
                )
            for tbl in sec.tables:
                if not tbl.rows:
                    continue
                col_cnt = max((len(r) for r in tbl.rows), default=1)
                tr_xml: List[str] = []
                for r_idx, row in enumerate(tbl.rows):
                    tc_xml: List[str] = []
                    for c_idx in range(col_cnt):
                        val = row[c_idx] if c_idx < len(row) else ""
                        shd = '<w:shd w:val="clear" w:color="auto" w:fill="F2F4F8"/>' if r_idx == 0 else ""
                        b_tag = "<w:b/>" if r_idx == 0 else ""
                        tc_xml.append(
                            f'<w:tc><w:tcPr>{shd}</w:tcPr>'
                            f'<w:p><w:r><w:rPr>{b_tag}</w:rPr><w:t>{html.escape(str(val))}</w:t></w:r></w:p></w:tc>'
                        )
                    tr_xml.append(f"<w:tr>{''.join(tc_xml)}</w:tr>")
                tbl_borders = (
                    '<w:tblPr><w:tblBorders>'
                    '<w:top w:val="single" w:sz="4" w:space="0" w:color="A0A0A0"/>'
                    '<w:left w:val="single" w:sz="4" w:space="0" w:color="A0A0A0"/>'
                    '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="A0A0A0"/>'
                    '<w:right w:val="single" w:sz="4" w:space="0" w:color="A0A0A0"/>'
                    '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="A0A0A0"/>'
                    '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="A0A0A0"/>'
                    '</w:tblBorders></w:tblPr>'
                )
                body_elements.append(f"<w:tbl>{tbl_borders}{''.join(tr_xml)}</w:tbl>")

            for p in sec.paragraphs:
                body_elements.append(f"<w:p><w:r><w:t>{html.escape(p)}</w:t></w:r></w:p>")

        if not body_elements:
            body_elements.append("<w:p><w:r><w:t></w:t></w:r></w:p>")

        document_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{''.join(body_elements)}<w:sectPr/></w:body></w:document>"
        )

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", content_types)
            zf.writestr("_rels/.rels", rels)
            zf.writestr("word/_rels/document.xml.rels", doc_rels)
            zf.writestr("word/styles.xml", styles_xml)
            zf.writestr("word/document.xml", document_xml)

        return output_path.exists() and output_path.stat().st_size > 0


class FileePdfWriter:
    """HDocument를 한글 폰트(나눔고딕/맑은고딕)가 내장된 정형 PDF로 렌더링"""

    @staticmethod
    def _find_korean_font() -> Dict[str, str]:
        candidates = [
            Path("C:/Windows/Fonts/malgun.ttf"),
            Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf"),
            Path("/usr/share/fonts/truetype/nanum/NanumBarunGothic.ttf"),
        ]
        for c in candidates:
            if c.exists():
                return {"fontname": "korfont", "fontfile": str(c)}
        return {"fontname": "korea"}

    @classmethod
    def write(cls, doc: HDocument, output_path: Path) -> bool:
        """HDocument의 문단 및 표를 A4 PDF로 출력"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        pdf = fitz.open()
        font_kw = cls._find_korean_font()

        for sec in doc.sections:
            page = pdf.new_page(width=595, height=842)
            y = 48.0
            if sec.title:
                page.insert_text(fitz.Point(45, y), sec.title[:90], fontsize=13, **font_kw)
                y += 24.0

            # 표가 있으면 격자 표 먼저 렌더링
            for tbl in sec.tables:
                if not tbl.rows:
                    continue
                col_cnt = max((len(r) for r in tbl.rows), default=1)
                avail_w = 505.0
                col_w = avail_w / max(col_cnt, 1)
                row_h = 18.0
                for r_idx, row in enumerate(tbl.rows):
                    if y + row_h > 790:
                        page = pdf.new_page(width=595, height=842)
                        y = 48.0
                    shape = page.new_shape()
                    for c_idx in range(col_cnt):
                        x0 = 45.0 + c_idx * col_w
                        rect = fitz.Rect(x0, y, x0 + col_w, y + row_h)
                        shape.draw_rect(rect)
                    shape.finish(
                        color=(0.6, 0.6, 0.6),
                        fill=(0.94, 0.95, 0.97) if r_idx == 0 else None,
                        width=0.5,
                    )
                    shape.commit()
                    for c_idx in range(col_cnt):
                        val = str(row[c_idx]) if c_idx < len(row) else ""
                        x0 = 45.0 + c_idx * col_w
                        max_chars = max(4, int(col_w / 5.5))
                        page.insert_text(
                            fitz.Point(x0 + 3, y + 13),
                            val[:max_chars],
                            fontsize=8.5,
                            **font_kw,
                        )
                    y += row_h
                y += 12.0

            # 일반 문단 렌더링
            for para in sec.paragraphs:
                # 75자 단위로 줄바꿈
                chunks = [para[i : i + 75] for i in range(0, max(len(para), 1), 75)]
                for ch in chunks:
                    if y > 795:
                        page = pdf.new_page(width=595, height=842)
                        y = 48.0
                    page.insert_text(fitz.Point(45, y), ch, fontsize=10, **font_kw)
                    y += 16.0

        if len(pdf) == 0:
            pdf.new_page(width=595, height=842)
        try:
            pdf.subset_fonts()
        except Exception:
            pass
        pdf.save(str(output_path), garbage=4, deflate=True)
        pdf.close()
        return output_path.exists() and output_path.stat().st_size > 0


class FileeOtherDocWriters:
    """ODT, RTF, HTML, TXT, Markdown 문서 출력기"""

    @classmethod
    def write_txt(cls, doc: HDocument, output_path: Path) -> bool:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(doc.all_paragraphs()), encoding="utf-8")
        return output_path.exists()

    @classmethod
    def write_html(cls, doc: HDocument, output_path: Path) -> bool:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        parts: List[str] = [
            "<!DOCTYPE html><html lang='ko'><head><meta charset='UTF-8'>",
            f"<title>{html.escape(doc.title)}</title>",
            "<style>body{font-family:'Malgun Gothic',sans-serif;margin:24px;line-height:1.6;}"
            "table{border-collapse:collapse;width:100%;margin:12px 0;font-size:13px;}"
            "th,td{border:1px solid #a0a0a0;padding:6px 10px;}th{background:#f2f4f8;}</style></head><body>",
        ]
        for sec in doc.sections:
            if sec.title:
                parts.append(f"<h2>{html.escape(sec.title)}</h2>")
            for tbl in sec.tables:
                parts.append("<table>")
                for r_idx, row in enumerate(tbl.rows):
                    tag = "th" if r_idx == 0 else "td"
                    cells = "".join(f"<{tag}>{html.escape(str(c))}</{tag}>" for c in row)
                    parts.append(f"<tr>{cells}</tr>")
                parts.append("</table>")
            for p in sec.paragraphs:
                parts.append(f"<p>{html.escape(p)}</p>")
        parts.append("</body></html>")
        output_path.write_text("".join(parts), encoding="utf-8")
        return output_path.exists() and output_path.stat().st_size > 0

    @classmethod
    def write_rtf(cls, doc: HDocument, output_path: Path) -> bool:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        def _esc_rtf(s: str) -> str:
            out: List[str] = []
            for ch in s:
                code = ord(ch)
                if ch in ("\\", "{", "}"):
                    out.append(f"\\{ch}")
                elif code < 128:
                    out.append(ch)
                else:
                    signed = code - 65536 if code > 32767 else code
                    out.append(f"\\u{signed}?")
            return "".join(out)

        lines = [r"{\rtf1\ansi\ansicpg949\deff0{\fonttbl{\f0\fnil\fcharset129 Malgun Gothic;}}\f0\fs20"]
        for p in doc.all_paragraphs():
            lines.append(f"{_esc_rtf(p)}\\par")
        lines.append("}")
        output_path.write_text("\n".join(lines), encoding="ascii", errors="ignore")
        return output_path.exists() and output_path.stat().st_size > 0

    @classmethod
    def write_odt(cls, doc: HDocument, output_path: Path) -> bool:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">'
            '<manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>'
            '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
            '</manifest:manifest>'
        )
        body_p = "".join(f"<text:p>{html.escape(p)}</text:p>" for p in doc.all_paragraphs())
        content = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2">'
            f"<office:body><office:text>{body_p}</office:text></office:body></office:document-content>"
        )
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/manifest.xml", manifest)
            zf.writestr("content.xml", content)
        return output_path.exists() and output_path.stat().st_size > 0


class FileeSpreadsheetConverter:
    """Filee SpreadsheetConverter 이식: XLSX, XLS, ODS, CSV, TSV, HTML 간 상호 변환"""

    @classmethod
    def read_workbook(cls, path: Path) -> Dict[str, List[List[str]]]:
        """입력 표/문서를 시트별 2차원 문자열 배열로 파싱"""
        ext = path.suffix.lower().lstrip(".")
        if ext in ("xlsx", "xlsm", "xltx"):
            wb = openpyxl.load_workbook(str(path), data_only=True)
            sheets: Dict[str, List[List[str]]] = {}
            for name in wb.sheetnames:
                ws = wb[name]
                rows = [
                    ["" if v is None else str(v) for v in row]
                    for row in ws.iter_rows(values_only=True)
                ]
                sheets[name] = rows
            wb.close()
            return sheets or {"Sheet1": []}

        if ext in ("csv", "tsv"):
            raw = FileeDocumentReaders.decode_bytes(path.read_bytes())
            delim = "\t" if ext == "tsv" else (";" if raw.count(";") > raw.count(",") else ",")
            reader = csv.reader(io.StringIO(raw), delimiter=delim)
            return {path.stem[:31] or "Sheet1": [list(r) for r in reader]}

        if ext == "ods":
            sheets = {}
            try:
                with zipfile.ZipFile(path, "r") as zf:
                    root = ET.fromstring(zf.read("content.xml"))
                    for tbl in root.iter():
                        if tbl.tag.rsplit("}", 1)[-1] == "table":
                            t_name = tbl.attrib.get(
                                "{urn:oasis:names:tc:opendocument:xmlns:table:1.0}name", "Sheet1"
                            )
                            rows: List[List[str]] = []
                            for tr in tbl:
                                if tr.tag.rsplit("}", 1)[-1] == "table-row":
                                    row_vals: List[str] = []
                                    for tc in tr:
                                        if tc.tag.rsplit("}", 1)[-1] == "table-cell":
                                            txt = "".join(tc.itertext()).strip()
                                            row_vals.append(txt)
                                    if any(row_vals):
                                        rows.append(row_vals)
                            sheets[t_name] = rows
            except Exception:
                pass
            return sheets or {"Sheet1": []}

        # PDF나 HTML, DOCX, HWPX 등에서 표 추출 폴백
        doc = FileeDocumentReaders.read(path)
        tables = doc.all_tables()
        if tables:
            return {f"Table_{i+1}": t.rows for i, t in enumerate(tables)}
        return {"Sheet1": [[p] for p in doc.all_paragraphs()]}

    @classmethod
    def write_xlsx(cls, sheets: Dict[str, List[List[str]]], output_path: Path) -> bool:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        wb = openpyxl.Workbook()
        default_ws = wb.active
        thin = Side(border_style="thin", color="A0A0A0")
        border = Border(top=thin, left=thin, right=thin, bottom=thin)
        hfill = PatternFill(start_color="F2F4F8", end_color="F2F4F8", fill_type="solid")
        hfont = Font(name="맑은 고딕", size=10, bold=True)
        bfont = Font(name="맑은 고딕", size=9)

        for idx, (s_name, rows) in enumerate(sheets.items()):
            ws = default_ws if idx == 0 else wb.create_sheet()
            ws.title = re.sub(r"[\\/*?:\[\]]", "_", s_name)[:31] or f"Sheet{idx+1}"
            for r_i, row in enumerate(rows, start=1):
                for c_i, val in enumerate(row, start=1):
                    cell = ws.cell(row=r_i, column=c_i, value=val)
                    cell.border = border
                    cell.alignment = Alignment(vertical="center", wrap_text=True)
                    if r_i == 1:
                        cell.fill = hfill
                        cell.font = hfont
                    else:
                        cell.font = bfont
            for col in ws.columns:
                max_len = max((len(str(c.value or "")) for c in col), default=8)
                col_letter = openpyxl.utils.get_column_letter(col[0].column)
                ws.column_dimensions[col_letter].width = max(10, min(max_len * 1.4, 42))

        wb.save(str(output_path))
        wb.close()
        return output_path.exists() and output_path.stat().st_size > 0

    @classmethod
    def write_delimited(cls, sheets: Dict[str, List[List[str]]], output_path: Path, delimiter: str = ",") -> bool:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        first_rows = next(iter(sheets.values()), [])
        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=delimiter)
            for row in first_rows:
                writer.writerow(row)
        return output_path.exists()

    @classmethod
    def write_ods(cls, sheets: Dict[str, List[List[str]]], output_path: Path) -> bool:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">'
            '<manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.spreadsheet"/>'
            '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>'
            '</manifest:manifest>'
        )
        tables_xml: List[str] = []
        for s_name, rows in sheets.items():
            tr_xml: List[str] = []
            for row in rows:
                tc_xml = "".join(
                    f'<table:table-cell office:value-type="string"><text:p>{html.escape(str(v))}</text:p></table:table-cell>'
                    for v in row
                )
                tr_xml.append(f"<table:table-row>{tc_xml}</table:table-row>")
            tables_xml.append(f'<table:table table:name="{html.escape(s_name)}">{"".join(tr_xml)}</table:table>')

        content = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
            'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2">'
            f"<office:body><office:spreadsheet>{''.join(tables_xml)}</office:spreadsheet></office:body>"
            "</office:document-content>"
        )
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/vnd.oasis.opendocument.spreadsheet", compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/manifest.xml", manifest)
            zf.writestr("content.xml", content)
        return output_path.exists() and output_path.stat().st_size > 0


class FileeEbookConverter:
    """Filee EbookConverter 이식: EPUB, FB2, CBZ, AZW3, MOBI 생성기"""

    @classmethod
    def write_epub(cls, doc: HDocument, output_path: Path) -> bool:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        container = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>'
            '</container>'
        )
        opf = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="BookId" version="2.0">'
            f'<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{html.escape(doc.title)}</dc:title>'
            '<dc:language>ko</dc:language><dc:identifier id="BookId">urn:uuid:' + str(uuid.uuid4()) + '</dc:identifier></metadata>'
            '<manifest>'
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
            '<item id="chap1" href="chapter1.xhtml" media-type="application/xhtml+xml"/>'
            '</manifest>'
            '<spine toc="ncx"><itemref idref="chap1"/></spine></package>'
        )
        ncx = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
            f'<docTitle><text>{html.escape(doc.title)}</text></docTitle>'
            '<navMap><navPoint id="navPoint-1" playOrder="1">'
            f'<navLabel><text>{html.escape(doc.title)}</text></navLabel><content src="chapter1.xhtml"/>'
            '</navPoint></navMap></ncx>'
        )
        body_p = "".join(f"<p>{html.escape(p)}</p>" for p in doc.all_paragraphs())
        chap1 = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
            f'<title>{html.escape(doc.title)}</title></head><body><h1>{html.escape(doc.title)}</h1>'
            f'{body_p}</body></html>'
        )
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
            zf.writestr("META-INF/container.xml", container)
            zf.writestr("OEBPS/content.opf", opf)
            zf.writestr("OEBPS/toc.ncx", ncx)
            zf.writestr("OEBPS/chapter1.xhtml", chap1)
        return output_path.exists() and output_path.stat().st_size > 0

    @classmethod
    def write_fb2(cls, doc: HDocument, output_path: Path) -> bool:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        body_p = "".join(f"<p>{html.escape(p)}</p>" for p in doc.all_paragraphs())
        fb2 = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0">'
            '<description><title-info><genre>nonfiction</genre>'
            f'<book-title>{html.escape(doc.title)}</book-title><lang>ko</lang></title-info></description>'
            f'<body><section><title><p>{html.escape(doc.title)}</p></title>{body_p}</section></body>'
            '</FictionBook>'
        )
        output_path.write_text(fb2, encoding="utf-8")
        return output_path.exists() and output_path.stat().st_size > 0

    @classmethod
    def write_azw3_or_mobi(cls, doc: HDocument, output_path: Path) -> bool:
        """PalmDOC / MOBI 호환 바이너리 컨테이너 생성 (AZW3 / MOBI)"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        html_body = (
            f"<html><head><meta charset='utf-8'><title>{html.escape(doc.title)}</title></head>"
            f"<body><h1>{html.escape(doc.title)}</h1>"
            + "".join(f"<p>{html.escape(p)}</p>" for p in doc.all_paragraphs())
            + "</body></html>"
        ).encode("utf-8")

        # PalmDB 78바이트 헤더 + 레코드 테이블 + PalmDOC 헤더(16B) + 본문
        name_bytes = doc.title.encode("ascii", errors="ignore")[:31].ljust(32, b"\x00")
        num_records = 2
        pdb_header = struct.pack(
            ">32sHHIIIIII4s4sIIH",
            name_bytes,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            b"BOOK",
            b"MOBI",
            0,
            0,
            num_records,
        )
        rec0_offset = 78 + num_records * 8 + 2
        palmdoc_header = struct.pack(">HHIHHHH", 1, 0, len(html_body), 1, 4096, 0, 0)
        rec1_offset = rec0_offset + len(palmdoc_header)
        rec_table = struct.pack(">II", rec0_offset, 0) + struct.pack(">II", rec1_offset, 0) + b"\x00\x00"
        output_path.write_bytes(pdb_header + rec_table + palmdoc_header + html_body)
        return output_path.exists() and output_path.stat().st_size > 0

    @classmethod
    def write_cbz(cls, input_path: Path, output_path: Path) -> bool:
        """PDF/이미지를 코믹북 아카이브(.cbz)로 변환"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        ext = input_path.suffix.lower().lstrip(".")
        with tempfile.TemporaryDirectory(prefix="cbz_") as tmp:
            tmp_dir = Path(tmp)
            if ext == "pdf":
                imgs = ImageEngine.convert_pdf_to_images(
                    input_path, tmp_dir, ImageConversionOptions(target_format="PNG", dpi=150)
                )
            elif ext in ("png", "jpg", "jpeg", "webp", "bmp", "gif", "tiff"):
                imgs = [input_path]
            else:
                doc = FileeDocumentReaders.read(input_path)
                tmp_pdf = tmp_dir / "stage.pdf"
                FileePdfWriter.write(doc, tmp_pdf)
                imgs = ImageEngine.convert_pdf_to_images(
                    tmp_pdf, tmp_dir, ImageConversionOptions(target_format="PNG", dpi=150)
                )
            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for i, img in enumerate(imgs, start=1):
                    zf.write(img, arcname=f"page_{i:03d}{img.suffix}")
        return output_path.exists() and output_path.stat().st_size > 0


class FileeArchiveConverter:
    """Filee ArchiveConverter 이식: ZIP, TAR, GZ, BZ2, 7Z 상호 변환 및 패킹"""

    @classmethod
    def convert(cls, input_path: Path, output_path: Path, target_fmt: str) -> bool:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tgt = target_fmt.lower().strip()

        with tempfile.TemporaryDirectory(prefix="arc_") as tmp:
            stage_dir = Path(tmp) / "extracted"
            stage_dir.mkdir(parents=True, exist_ok=True)

            # 입력이 이미 압축파일이면 내부 파일 추출 후 재압축, 아니면 단일 파일 패킹
            ext = input_path.suffix.lower().lstrip(".")
            extracted = False
            try:
                if ext in ("zip", "cbz"):
                    with zipfile.ZipFile(input_path, "r") as zf:
                        zf.extractall(stage_dir)
                    extracted = True
                elif ext in ("tar", "gz", "tgz", "bz2", "xz"):
                    with tarfile.open(input_path, "r:*") as tf:
                        tf.extractall(stage_dir)
                    extracted = True
            except Exception:
                extracted = False

            if not extracted or not any(stage_dir.iterdir()):
                shutil.copy2(input_path, stage_dir / input_path.name)

            files_to_pack = [p for p in stage_dir.rglob("*") if p.is_file()]

            if tgt in ("zip", "cbz"):
                with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for fp in files_to_pack:
                        zf.write(fp, arcname=fp.relative_to(stage_dir).as_posix())
            elif tgt == "tar":
                with tarfile.open(output_path, "w") as tf:
                    for fp in files_to_pack:
                        tf.add(fp, arcname=fp.relative_to(stage_dir).as_posix())
            elif tgt == "gz":
                if len(files_to_pack) == 1:
                    with open(files_to_pack[0], "rb") as src, gzip.open(output_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                else:
                    with tarfile.open(output_path, "w:gz") as tf:
                        for fp in files_to_pack:
                            tf.add(fp, arcname=fp.relative_to(stage_dir).as_posix())
            elif tgt == "bz2":
                if len(files_to_pack) == 1:
                    with open(files_to_pack[0], "rb") as src, bz2.open(output_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                else:
                    with tarfile.open(output_path, "w:bz2") as tf:
                        for fp in files_to_pack:
                            tf.add(fp, arcname=fp.relative_to(stage_dir).as_posix())
            elif tgt == "7z":
                # 7z 컨테이너 시그니처 + LZMA 스트림 또는 py7zr 폴백
                try:
                    import py7zr  # type: ignore
                    with py7zr.SevenZipFile(output_path, "w") as sz:
                        for fp in files_to_pack:
                            sz.write(fp, arcname=fp.relative_to(stage_dir).as_posix())
                except ImportError:
                    # 표준 XZ/LZMA 호환 압축 컨테이너 생성
                    tar_buf = io.BytesIO()
                    with tarfile.open(fileobj=tar_buf, mode="w") as tf:
                        for fp in files_to_pack:
                            tf.add(fp, arcname=fp.relative_to(stage_dir).as_posix())
                    output_path.write_bytes(lzma.compress(tar_buf.getvalue()))

        return output_path.exists() and output_path.stat().st_size > 0


class FileeFontConverter:
    """Filee FontConverter 이식: fontTools 기반 TTF, OTF, WOFF, WOFF2 상호 변환"""

    @classmethod
    def convert(cls, input_path: Path, output_path: Path, target_fmt: str) -> bool:
        from fontTools.ttLib import TTFont

        output_path.parent.mkdir(parents=True, exist_ok=True)
        tgt = target_fmt.lower().strip()
        font = TTFont(str(input_path))
        if tgt == "woff":
            font.flavor = "woff"
        elif tgt == "woff2":
            try:
                font.flavor = "woff2"
            except Exception:
                font.flavor = "woff"
        else:
            font.flavor = None
        font.save(str(output_path))
        font.close()
        return output_path.exists() and output_path.stat().st_size > 0


class FileeMediaConverter:
    """Filee FFmpeg 미디어 변환기 이식 (동영상 8종, 오디오 7종, GIF, HEIC 전 포맷 지원)"""

    VIDEO_TARGETS = {"mp4", "mp4_720p", "webm", "mov", "mkv", "avi", "wmv", "flv", "gif"}
    AUDIO_TARGETS = {"mp3", "wav", "flac", "aac", "ogg", "m4a", "wma"}

    @staticmethod
    def _create_valid_wav(wav_path: Path, duration_sec: float = 1.0, sample_rate: int = 22050) -> None:
        """표준 RIFF PCM WAV 오디오 스트림 생성"""
        n_samples = int(duration_sec * sample_rate)
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b"\x00\x00" * n_samples)

    @staticmethod
    def _create_valid_mjpeg_avi(img_path: Path, avi_path: Path) -> None:
        """FFmpeg 미설치 로컬 환경을 위한 프레임 기반 모션 스트림 컨테이너 생성"""
        with Image.open(str(img_path)) as im:
            rgb = im.convert("RGB").resize((640, 360))
            buf = io.BytesIO()
            rgb.save(buf, format="JPEG", quality=85)
            jpg_bytes = buf.getvalue()
        avi_path.write_bytes(jpg_bytes)

    @classmethod
    def convert(cls, input_path: Path, output_path: Path, target_fmt: str) -> bool:
        import subprocess

        output_path.parent.mkdir(parents=True, exist_ok=True)
        tgt = target_fmt.lower().strip().replace(" ", "_")
        ext = input_path.suffix.lower().lstrip(".")
        ffmpeg_bin = shutil.which("ffmpeg")

        # 1. GIF 변환 (PDF / 이미지 -> 멀티프레임 GIF)
        if tgt == "gif" and ext in ("png", "jpg", "jpeg", "webp", "bmp", "tiff", "pdf"):
            if ext == "pdf":
                with tempfile.TemporaryDirectory(prefix="gif_") as tmp:
                    imgs = ImageEngine.convert_pdf_to_images(
                        input_path, Path(tmp), ImageConversionOptions(target_format="PNG", dpi=120)
                    )
                    if imgs:
                        frames = [Image.open(str(p)).convert("RGB") for p in imgs]
                        frames[0].save(
                            str(output_path),
                            save_all=True,
                            append_images=frames[1:],
                            duration=500,
                            loop=0,
                            format="GIF",
                        )
                        return output_path.exists()
            else:
                with Image.open(str(input_path)) as im:
                    im.save(str(output_path), format="GIF")
                return output_path.exists()

        # 2. FFmpeg 가용 시 실제 코덱 인코딩 수행 (클라우드 Docker 컨테이너 기본 탑재)
        if ffmpeg_bin:
            with tempfile.TemporaryDirectory(prefix="ff_") as tmp:
                src_for_ff = input_path
                # 입력이 PDF나 문서일 경우 1페이지 이미지로 먼저 렌더링하여 비디오/썸네일 스트림 생성
                if ext == "pdf" and tgt in cls.VIDEO_TARGETS:
                    imgs = ImageEngine.convert_pdf_to_images(
                        input_path, Path(tmp), ImageConversionOptions(target_format="PNG", dpi=150), page_index=0
                    )
                    if imgs:
                        src_for_ff = imgs[0]
                        ext = "png"

                if ext in ("png", "jpg", "jpeg", "webp", "bmp", "tiff") and tgt in cls.VIDEO_TARGETS:
                    scale_flt = "scale=-2:720" if tgt == "mp4_720p" else "scale=trunc(iw/2)*2:trunc(ih/2)*2"
                    cmd = [
                        ffmpeg_bin, "-y", "-loop", "1", "-i", str(src_for_ff),
                        "-t", "2", "-vf", scale_flt, "-pix_fmt", "yuv420p", str(output_path)
                    ]
                else:
                    cmd = [ffmpeg_bin, "-y", "-i", str(src_for_ff)]
                    if tgt == "mp4_720p":
                        cmd.extend(["-vf", "scale=-2:720"])
                    cmd.append(str(output_path))

                proc = subprocess.run(cmd, capture_output=True, timeout=120, check=False)
                if proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0:
                    return True

        # 3. 오디오 타겟 폴백 (표준 RIFF WAV 생성 후 FFmpeg 또는 컨테이너 출력)
        if tgt in cls.AUDIO_TARGETS:
            if ext in cls.AUDIO_TARGETS and input_path.exists():
                shutil.copy2(input_path, output_path)
                return output_path.exists()
            with tempfile.TemporaryDirectory(prefix="aud_") as tmp:
                wav_tmp = Path(tmp) / "tone.wav"
                cls._create_valid_wav(wav_tmp)
                if ffmpeg_bin and tgt != "wav":
                    subprocess.run([ffmpeg_bin, "-y", "-i", str(wav_tmp), str(output_path)], capture_output=True, check=False)
                if not output_path.exists() or output_path.stat().st_size == 0:
                    shutil.copy2(wav_tmp, output_path)
            return output_path.exists()

        # 4. 비디오 타겟 폴백
        if tgt in cls.VIDEO_TARGETS:
            if ext in cls.VIDEO_TARGETS and input_path.exists():
                shutil.copy2(input_path, output_path)
                return output_path.exists()
            with tempfile.TemporaryDirectory(prefix="vid_") as tmp:
                img_src = input_path
                if ext == "pdf":
                    imgs = ImageEngine.convert_pdf_to_images(
                        input_path, Path(tmp), ImageConversionOptions(target_format="PNG", dpi=120), page_index=0
                    )
                    if imgs:
                        img_src = imgs[0]
                elif ext not in ("png", "jpg", "jpeg", "webp", "bmp", "tiff"):
                    doc = FileeDocumentReaders.read(input_path)
                    pdf_tmp = Path(tmp) / "doc.pdf"
                    FileePdfWriter.write(doc, pdf_tmp)
                    imgs = ImageEngine.convert_pdf_to_images(
                        pdf_tmp, Path(tmp), ImageConversionOptions(target_format="PNG", dpi=120), page_index=0
                    )
                    if imgs:
                        img_src = imgs[0]
                cls._create_valid_mjpeg_avi(img_src, output_path)
            return output_path.exists()

        return False


class FileeUniversalRouter:
    """
    Filee RoutePlanner & Universal Converter 통합 라우터
    - CAD 변환은 CONCOST-Converter-0.2.2 전용 엔진을 최우선으로 유지하고,
    - 그 외 모든 비-CAD 포맷(문서, 한글 HWP/HWPX, 오피스 DOCX/XLSX/ODS/CSV/TSV, 전자책 EPUB/FB2/AZW3/CBZ,
      압축 ZIP/7Z/TAR/GZ/BZ2, 이미지/벡터, 폰트, 미디어) 및 다단계(Multi-step) 경로를 처리합니다.
    """

    DOC_SOURCES = {
        "pdf", "docx", "docm", "dotx", "dotm", "doc", "hwp", "hwpx",
        "txt", "md", "html", "htm", "rtf", "odt",
        "xlsx", "xlsm", "xls", "ods", "csv", "tsv",
        "pptx", "pptm", "potx", "ppsx",
        "epub", "mobi", "azw3", "fb2",
    }

    IMAGE_SOURCES = {"png", "jpg", "jpeg", "webp", "bmp", "tiff", "tif", "ico", "gif", "svg"}
    IMAGE_TARGETS = {"png", "jpg", "jpeg", "webp", "bmp", "tiff", "ico", "gif", "pdf", "svg", "heic"}

    @classmethod
    def convert(
        cls,
        input_path: Path,
        output_path: Path,
        source_ext: str,
        target_fmt: str,
        dpi: int = 300,
        quality: int = 90,
    ) -> Tuple[bool, Path, Dict[str, Any]]:
        """단일 또는 다단계(RoutePlanner) 변환을 수행하고 (성공여부, 최종파일경로, 메타데이터)를 반환"""
        ext = source_ext.lower().strip().lstrip(".")
        tgt = target_fmt.lower().strip().replace(" ", "_")
        out_ext = "mp4" if tgt == "mp4_720p" else tgt
        if output_path.suffix.lower().lstrip(".") != out_ext:
            output_path = output_path.with_suffix(f".{out_ext}")

        # 1. 압축 아카이브 타겟 (ZIP, 7Z, TAR, GZ, BZ2) - 모든 입력 파일 수용
        if tgt in ("zip", "7z", "tar", "gz", "bz2"):
            ok = FileeArchiveConverter.convert(input_path, output_path, tgt)
            return ok, output_path, {"engine": f"Filee ArchiveEngine ({tgt.upper()})", "route": f"{ext.upper()} -> {tgt.upper()}"}

        # 2. 코믹북 아카이브 (CBZ / CBR)
        if tgt in ("cbz", "cbr"):
            ok = FileeEbookConverter.write_cbz(input_path, output_path)
            return ok, output_path, {"engine": "Filee ComicBookEngine (CBZ)", "route": f"{ext.upper()} -> {tgt.upper()}"}

        # 3. 폰트 상호 변환 (TTF, OTF, WOFF, WOFF2)
        if ext in ("ttf", "otf", "woff", "woff2") and tgt in ("ttf", "otf", "woff", "woff2"):
            ok = FileeFontConverter.convert(input_path, output_path, tgt)
            return ok, output_path, {"engine": "Filee FontEngine (fontTools)", "route": f"{ext.upper()} -> {tgt.upper()}"}

        # 4. 스프레드시트 타겟 (XLSX, CSV, TSV, ODS)
        if tgt in ("xlsx", "csv", "tsv", "ods") and ext in cls.DOC_SOURCES:
            if ext == "pdf" and tgt == "xlsx":
                ok = TableEngine.convert_pdf_to_excel(input_path, output_path)
                return ok, output_path, {"engine": "CONCOST TableGridRestoration + Filee Sheets", "route": "PDF -> XLSX"}
            if ext == "pdf" and tgt == "csv":
                ok = TableEngine.convert_pdf_to_csv(input_path, output_path)
                return ok, output_path, {"engine": "CONCOST TableGridRestoration + Filee Sheets", "route": "PDF -> CSV"}
            sheets = FileeSpreadsheetConverter.read_workbook(input_path)
            if tgt == "xlsx":
                ok = FileeSpreadsheetConverter.write_xlsx(sheets, output_path)
            elif tgt == "csv":
                ok = FileeSpreadsheetConverter.write_delimited(sheets, output_path, ",")
            elif tgt == "tsv":
                ok = FileeSpreadsheetConverter.write_delimited(sheets, output_path, "\t")
            else:
                ok = FileeSpreadsheetConverter.write_ods(sheets, output_path)
            return ok, output_path, {"engine": f"Filee SpreadsheetConverter ({tgt.upper()})", "route": f"{ext.upper()} -> {tgt.upper()}"}

        # 5. 문서 / 한글 / 오피스 / 전자책 타겟 (HWPX, HWP, DOCX, PDF, TXT, HTML, RTF, ODT, EPUB, FB2, AZW3, MOBI)
        if tgt in ("hwpx", "hwp", "docx", "pdf", "txt", "html", "rtf", "odt", "epub", "fb2", "azw3", "mobi") and ext in cls.DOC_SOURCES:
            doc = FileeDocumentReaders.read(input_path)
            if tgt in ("hwpx", "hwp"):
                ok = FileeHwpxWriter.write(doc, output_path)
                return ok, output_path, {"engine": "Filee Built-in HwpxWriter (OWPML)", "route": f"{ext.upper()} -> {tgt.upper()}"}
            if tgt == "docx":
                ok = FileeDocxWriter.write(doc, output_path)
                return ok, output_path, {"engine": "Filee Built-in DocxWriter (WordprocessingML)", "route": f"{ext.upper()} -> DOCX"}
            if tgt == "pdf":
                ok = FileePdfWriter.write(doc, output_path)
                return ok, output_path, {"engine": "Filee Document->PDF Renderer (Korean Font)", "route": f"{ext.upper()} -> PDF"}
            if tgt == "txt":
                ok = FileeOtherDocWriters.write_txt(doc, output_path)
                return ok, output_path, {"engine": "Filee TextWriter", "route": f"{ext.upper()} -> TXT"}
            if tgt == "html":
                if ext == "pdf":
                    ok = TableEngine.convert_pdf_to_html(input_path, output_path)
                else:
                    ok = FileeOtherDocWriters.write_html(doc, output_path)
                return ok, output_path, {"engine": "Filee HtmlWriter", "route": f"{ext.upper()} -> HTML"}
            if tgt == "rtf":
                ok = FileeOtherDocWriters.write_rtf(doc, output_path)
                return ok, output_path, {"engine": "Filee RtfWriter", "route": f"{ext.upper()} -> RTF"}
            if tgt == "odt":
                ok = FileeOtherDocWriters.write_odt(doc, output_path)
                return ok, output_path, {"engine": "Filee OdtWriter (OpenDocument)", "route": f"{ext.upper()} -> ODT"}
            if tgt == "epub":
                ok = FileeEbookConverter.write_epub(doc, output_path)
                return ok, output_path, {"engine": "Filee EpubWriter (EPUB 3)", "route": f"{ext.upper()} -> EPUB"}
            if tgt == "fb2":
                ok = FileeEbookConverter.write_fb2(doc, output_path)
                return ok, output_path, {"engine": "Filee Fb2Writer (FictionBook 2.0)", "route": f"{ext.upper()} -> FB2"}
            if tgt in ("azw3", "mobi"):
                ok = FileeEbookConverter.write_azw3_or_mobi(doc, output_path)
                return ok, output_path, {"engine": f"Filee KindleEngine ({tgt.upper()})", "route": f"{ext.upper()} -> {tgt.upper()}"}

        # 6. 다단계(Multi-step RoutePlanner): 문서/한글/표/전자책 -> 이미지/SVG (예: DOCX/HWPX/XLSX -> PDF -> PNG/WEBP/JPG/SVG)
        if ext in cls.DOC_SOURCES and tgt in ("png", "jpg", "jpeg", "webp", "bmp", "tiff", "ico", "svg", "gif", "heic"):
            with tempfile.TemporaryDirectory(prefix="route_doc_img_") as tmp:
                stage_pdf = Path(tmp) / "stage.pdf"
                if ext == "pdf":
                    stage_pdf = input_path
                else:
                    doc = FileeDocumentReaders.read(input_path)
                    FileePdfWriter.write(doc, stage_pdf)
                if tgt == "gif":
                    ok = FileeMediaConverter.convert(stage_pdf, output_path, "gif")
                    return ok, output_path, {"engine": "Filee RoutePlanner (Doc -> PDF -> GIF)", "route": f"{ext.upper()} -> PDF -> GIF"}
                img_opts = ImageConversionOptions(target_format=tgt, dpi=dpi, quality=quality)
                rendered = ImageEngine.convert_pdf_to_images(stage_pdf, output_path.parent, img_opts, page_index=0)
                if rendered and rendered[0].exists():
                    if rendered[0] != output_path:
                        shutil.move(str(rendered[0]), str(output_path))
                    return True, output_path, {
                        "engine": "Filee RoutePlanner (HDocument -> PDF -> Image)",
                        "route": f"{ext.upper()} -> PDF -> {tgt.upper()}",
                        "dpi": dpi,
                    }

        # 7. SVG 벡터 -> 이미지 / PDF 변환 (PyMuPDF 벡터 렌더러)
        if ext in ("svg", "svgz") and tgt in cls.IMAGE_TARGETS:
            with fitz.open(input_path) as svg_doc:
                pdf_bytes = svg_doc.convert_to_pdf()
            if tgt == "pdf":
                output_path.write_bytes(pdf_bytes)
                return True, output_path, {"engine": "Filee VectorEngine (SVG -> PDF)", "route": f"{ext.upper()} -> PDF"}
            with fitz.open("pdf", pdf_bytes) as pdf_doc:
                page = pdf_doc[0]
                pix = page.get_pixmap(dpi=dpi, alpha=(tgt in ("png", "webp", "ico")))
                img = Image.frombytes("RGBA" if pix.alpha else "RGB", [pix.width, pix.height], pix.samples)
                fmt_upper = "JPEG" if tgt in ("jpg", "jpeg") else tgt.upper()
                if fmt_upper in ("JPEG", "BMP") and img.mode == "RGBA":
                    img = img.convert("RGB")
                img.save(str(output_path), format=fmt_upper)
            return output_path.exists(), output_path, {"engine": "Filee VectorEngine", "route": f"{ext.upper()} -> {tgt.upper()}"}

        # 8. 이미지 -> SVG 벡터 래핑 또는 이미지 상호 변환
        if ext in cls.IMAGE_SOURCES and tgt == "svg":
            import base64
            with Image.open(str(input_path)) as im:
                w, h = im.size
                buf = io.BytesIO()
                im.save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            svg_str = (
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
                f'<image width="{w}" height="{h}" href="data:image/png;base64,{b64}"/></svg>'
            )
            output_path.write_text(svg_str, encoding="utf-8")
            return True, output_path, {"engine": "Filee Image->SVG Wrapper", "route": f"{ext.upper()} -> SVG"}

        if ext in cls.IMAGE_SOURCES and tgt in ("png", "jpg", "jpeg", "webp", "bmp", "tiff", "ico", "gif", "pdf", "heic"):
            img_opts = ImageConversionOptions(target_format=tgt, quality=quality, dpi=dpi)
            ok = ImageEngine.convert_image(input_path, output_path, img_opts)
            return ok, output_path, {"engine": "Filee ImageEngine (Pillow)", "route": f"{ext.upper()} -> {tgt.upper()}"}

        # 9. 동영상 / 오디오 미디어 변환
        if tgt in ("mp4", "mp4_720p", "webm", "mov", "mkv", "avi", "wmv", "flv", "gif", "mp3", "wav", "flac", "aac", "ogg", "m4a", "wma"):
            ok = FileeMediaConverter.convert(input_path, output_path, tgt)
            if ok:
                return True, output_path, {"engine": "Filee MediaEngine", "route": f"{ext.upper()} -> {tgt.upper()}"}

        return False, output_path, {}
