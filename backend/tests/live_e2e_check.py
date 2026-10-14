"""
라이브 E2E 검수: https://concost-total-converter.pages.dev 경유
로그인(D1) → 토큰 → /api/convert (Pages 프록시 → 터널 → 사내 엔진) → 다운로드 → 결과 파일 내용 검증
사용: python live_e2e_check.py [PDF경로 ...]
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

import ezdxf
import pymupdf

BASE = "https://concost-total-converter.pages.dev"
OUT = Path(__file__).resolve().parent / "e2e_out"
OUT.mkdir(exist_ok=True)
UA = {"User-Agent": "concost-e2e"}
DWG_SIGS = {"AC1015", "AC1018", "AC1021", "AC1024", "AC1027", "AC1032"}


def http(method: str, url: str, body: bytes | None = None, headers: dict | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers={**UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def login(lid: str, pwd: str) -> tuple[int, dict]:
    code, raw = http("POST", f"{BASE}/api/auth/login", json.dumps({"login_id": lid, "password": pwd}).encode(),
                     {"Content-Type": "application/json"})
    return code, json.loads(raw or b"{}")


def convert(token: str, pdf: Path, tgt: str) -> tuple[int, dict]:
    b = uuid.uuid4().hex
    body = b""
    for k, v in {"target_format": tgt, "scale_multiplier": "1.0", "auto_detect_scale": "false"}.items():
        body += f"--{b}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode()
    body += (f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{pdf.name}\"\r\n"
             f"Content-Type: application/pdf\r\n\r\n").encode("utf-8") + pdf.read_bytes() + f"\r\n--{b}--\r\n".encode()
    code, raw = http("POST", f"{BASE}/api/convert", body,
                     {"Content-Type": f"multipart/form-data; boundary={b}", "Authorization": f"Bearer {token}"})
    try:
        return code, json.loads(raw)
    except Exception:
        return code, {"raw": raw[:200].decode(errors="ignore")}


def source_stats(pdf: Path) -> str:
    with pymupdf.open(pdf) as d:
        p = d[0]
        return f"{len(d)}페이지, 1p 벡터 item {sum(len(x['items']) for x in p.get_drawings())}개, 단어 {len(p.get_text('words'))}개"


def check(name: str, ok: bool, detail: str, results: list) -> None:
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)


def main(pdfs: list[Path]) -> int:
    results: list[bool] = []
    print("== 보안 ==")
    code, _ = login("yjw", "wrong-pw")
    check("틀린 비밀번호 거부", code == 401, f"HTTP {code}", results)
    code, _ = convert("forged.token.x", pdfs[0], "dxf")
    check("위조 토큰으로 변환 거부", code == 401, f"HTTP {code}", results)

    code, data = login("yjw", "1234")
    check("D1 로그인(yjw/1234)", code == 200 and bool(data.get("token")), f"HTTP {code}", results)
    token = data.get("token", "")

    for pdf in pdfs:
        print(f"\n== {pdf.name} ({source_stats(pdf)}) ==")
        for tgt in ("dxf", "dwg", "xlsx", "csv", "txt", "svg", "png"):
            code, res = convert(token, pdf, tgt)
            if code != 200:
                check(f"PDF→{tgt.upper()} 변환", False, f"HTTP {code} {res}", results)
                continue
            dl = urllib.parse.quote(res["download_url"]) + "?t=" + urllib.parse.quote(token)
            dcode, raw = http("GET", BASE + dl)
            out = OUT / f"{pdf.stem}.{tgt}"
            out.write_bytes(raw)
            if dcode != 200 or not raw:
                check(f"PDF→{tgt.upper()} 다운로드", False, f"HTTP {dcode}", results)
                continue
            if tgt == "dxf":
                try:
                    doc = ezdxf.readfile(str(out))
                    msp = doc.modelspace()
                    types: dict[str, int] = {}
                    for e in msp:
                        types[e.dxftype()] = types.get(e.dxftype(), 0) + 1
                    audit = doc.audit()
                    ok = len(msp) > 0 and not audit.has_errors
                    check("PDF→DXF", ok, f"{len(raw):,}B, 엔터티 {len(msp):,}개 {types}, audit오류 {len(audit.errors)}", results)
                except Exception as e:
                    check("PDF→DXF", False, f"DXF 파싱 실패: {e}", results)
            elif tgt == "dwg":
                sig = raw[:6].decode("ascii", errors="ignore")
                ok = sig in DWG_SIGS
                check("PDF→DWG", ok, f"{len(raw):,}B, 시그니처 {sig}, 엔진 {res['metadata'].get('zwcad_engine')}, "
                      f"재열기 객체 {res['metadata'].get('entities')}", results)
            else:
                ok = len(raw) > 20
                check(f"PDF→{tgt.upper()}", ok, f"{len(raw):,}B, 엔진 {res.get('metadata', {}).get('engine')}", results)

    passed = sum(results)
    print(f"\n[결과] {passed}/{len(results)} PASS")
    return 0 if all(results) else 1


if __name__ == "__main__":
    args = [Path(a) for a in sys.argv[1:]] or [Path(r"e:/■ 개발_TF팀/변환 토탈웹/temp_verify/sample_drawing.pdf")]
    sys.exit(main(args))
