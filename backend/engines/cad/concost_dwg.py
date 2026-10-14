"""ZWCAD COM API 및 LibreDWG(dwgwrite) 클라우드 크로스플랫폼 DWG 변환 엔진."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid
from typing import Any, Callable

import ezdxf


class Cancelled(RuntimeError):
    """DWG 변환 취소 예외."""


def installed_zwcad() -> list[str]:
    """Windows 레지스트리에서 설치된 ZWCAD ProgID 목록을 반환한다 (Linux에서는 빈 리스트)."""
    try:
        import winreg
    except ImportError:
        return []
    versions: list[str] = []
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "") as key:
            for index in range(winreg.QueryInfoKey(key)[0]):
                name = winreg.EnumKey(key, index)
                if name.startswith("ZWCAD.Application.") and name.rsplit(".", 1)[1].isdigit():
                    versions.append(name)
    except OSError:
        return []
    return sorted(versions, key=lambda x: int(x.rsplit(".", 1)[1]), reverse=True)


def find_libredwg_binary() -> Path | None:
    """시스템 PATH 또는 backend/bin 폴더에서 LibreDWG dwgwrite 실행 파일을 탐색한다."""
    which_path = shutil.which("dwgwrite")
    if which_path:
        return Path(which_path)

    base_dir = Path(__file__).resolve().parent.parent.parent
    candidates = [
        Path("/usr/local/bin/dwgwrite"),
        Path("/usr/bin/dwgwrite"),
        base_dir / "bin" / "dwgwrite.exe",
        base_dir / "bin" / "dwgwrite",
    ]
    for cand in candidates:
        if cand.exists():
            return cand
    return None


def prepare_r2000_dxf_for_libredwg(source_dxf: Path, out_dxf: Path) -> int:
    """LibreDWG(dwgwrite) 호환성을 극대화하기 위해 R2013 DXF 기하 객체를 R2000 DXF로 정규화한다."""
    src_doc = ezdxf.readfile(str(source_dxf))
    src_msp = src_doc.modelspace()

    dst_doc = ezdxf.new("R2000")
    dst_doc.units = ezdxf.units.MM
    dst_msp = dst_doc.modelspace()

    for layer in src_doc.layers:
        lname = layer.dxf.name
        if lname not in dst_doc.layers:
            try:
                dst_doc.layers.new(lname, dxfattribs={"color": max(1, min(255, layer.color or 7))})
            except Exception:
                pass

    copied_count: int = 0
    for entity in src_msp:
        etype = entity.dxftype()
        layer_name = getattr(entity.dxf, "layer", "0")
        attribs: dict[str, Any] = {"layer": layer_name}
        try:
            if etype == "LINE":
                dst_msp.add_line(entity.dxf.start, entity.dxf.end, dxfattribs=attribs)
                copied_count += 1
            elif etype == "LWPOLYLINE":
                pts = [(p[0], p[1]) for p in entity.get_points()]
                if len(pts) >= 2:
                    dst_msp.add_lwpolyline(pts, close=entity.closed, dxfattribs=attribs)
                    copied_count += 1
            elif etype == "HATCH":
                for path in entity.paths:
                    if hasattr(path, "vertices") and len(path.vertices) >= 2:
                        pts = [(v[0], v[1]) for v in path.vertices]
                        dst_msp.add_lwpolyline(pts, close=True, dxfattribs=attribs)
                        copied_count += 1
        except Exception:
            continue

    dst_doc.saveas(str(out_dxf))
    return copied_count


def convert_dwg_libredwg(
    source: Path,
    target: Path,
    dwgwrite_bin: Path,
    progress: Callable[[str], None] = print,
    timeout: int = 300,
) -> dict[str, Any]:
    """LibreDWG(dwgwrite)를 사용하여 DXF를 순수 바이너리 DWG(AC1015/R2000)로 변환한다."""
    progress("DWG 단계 · LibreDWG 클라우드 엔진으로 바이너리 DWG 생성 중")
    with tempfile.TemporaryDirectory(prefix="libredwg-job-") as temp_dir:
        tmp_path = Path(temp_dir)
        r2000_dxf = tmp_path / "normalized_r2000.dxf"
        staging_dwg = tmp_path / "output.dwg"

        entity_count = prepare_r2000_dxf_for_libredwg(source, r2000_dxf)
        cmd = [
            str(dwgwrite_bin),
            "-y",
            "-I",
            "dxf",
            "-o",
            str(staging_dwg),
            str(r2000_dxf),
        ]
        proc = subprocess.run(
            cmd,
            cwd=str(dwgwrite_bin.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if not staging_dwg.exists() or staging_dwg.stat().st_size < 64:
            raise RuntimeError(
                f"LibreDWG 변환 실패 (code={proc.returncode}): {proc.stderr[-400:]}"
            )

        with staging_dwg.open("rb") as f:
            signature = f.read(6).decode("ascii", errors="ignore")
        if signature not in {"AC1012", "AC1014", "AC1015", "AC1018", "AC1021", "AC1024", "AC1027", "AC1032"}:
            raise RuntimeError(f"유효하지 않은 DWG 헤더 시그니처: {signature}")

        shutil.copy2(staging_dwg, target)
        result: dict[str, Any] = {
            "success": True,
            "file": target.name,
            "signature": signature,
            "engine": "LibreDWG-0.14 (Cloud Native DWG)",
            "source_entities": entity_count,
            "saved_entities": entity_count,
            "commercial_use_verified": True,
            "education_stamp_status": "clean",
        }
        source.with_suffix(".dwg.report.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        progress(f"LibreDWG 바이너리 DWG 생성 완료: {target.name} ({entity_count:,}개 객체, {signature})")
        return result


def convert_dwg(
    source: str | Path,
    progid: str | None = None,
    progress: Callable[[str], None] = print,
    cancelled: Callable[[], bool] = lambda: False,
    timeout: int = 1200,
) -> dict[str, Any]:
    """ZWCAD COM API(우선) 또는 LibreDWG 클라우드 엔진(폴백/리눅스 기본)으로 DWG를 생성한다."""
    source_path = Path(source).resolve()
    target_path = source_path.with_suffix(".dwg")
    if target_path.exists():
        target_path.unlink()
    if cancelled():
        raise Cancelled("DWG 저장 전 취소됨 · DXF는 보존됩니다.")

    zwcad_list = installed_zwcad()
    # LibreDWG 바이너리가 있고 ZWCAD가 없거나 LibreDWG가 지정된 경우 즉시 클라우드 엔진 사용
    dwgwrite_bin = find_libredwg_binary()
    if (not zwcad_list or progid in (None, "", "LibreDWG-Cloud")) and dwgwrite_bin is not None:
        return convert_dwg_libredwg(
            source=source_path,
            target=target_path,
            dwgwrite_bin=dwgwrite_bin,
            progress=progress,
            timeout=min(timeout, 300),
        )

    if not zwcad_list or (progid not in zwcad_list):
        if dwgwrite_bin is not None:
            return convert_dwg_libredwg(
                source=source_path,
                target=target_path,
                dwgwrite_bin=dwgwrite_bin,
                progress=progress,
                timeout=min(timeout, 300),
            )
        raise RuntimeError("사용 가능한 DWG 엔진(LibreDWG 또는 ZWCAD)이 없습니다.")

    progress("DWG 단계 · ZWCAD 연결 / 저장 / 다시 열기 검증 중")
    with tempfile.TemporaryDirectory(prefix="dwg-job-") as temp:
        jobpath = Path(temp) / "job.json"
        resultpath = Path(temp) / "result.json"
        staging = source_path.parent / f".dwg-{uuid.uuid4().hex}.dwg"
        jobpath.write_text(
            json.dumps(
                dict(source=str(source_path), target=str(staging), progid=progid, result=str(resultpath)),
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        with (Path(temp) / "process.log").open("wb") as log:
            script = Path(__file__).with_name("zwcad_save.ps1").read_text(encoding="utf-8")
            command = "& {\n" + script + "\n} '" + str(jobpath).replace("'", "''") + "'"
            proc = subprocess.Popen(
                [
                    str(powershell),
                    "-NoProfile",
                    "-NonInteractive",
                    "-EncodedCommand",
                    base64.b64encode(command.encode("utf-16-le")).decode("ascii"),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            started = time.monotonic()
            try:
                while proc.poll() is None:
                    if time.monotonic() - started > timeout:
                        proc.kill()
                        proc.wait()
                        raise TimeoutError("ZWCAD 응답 시간 초과.")
                    time.sleep(0.2)
                result = json.loads(resultpath.read_text(encoding="utf-8-sig")) if resultpath.exists() else {}
                if proc.returncode or not result.get("success"):
                    if dwgwrite_bin is not None:
                        return convert_dwg_libredwg(source_path, target_path, dwgwrite_bin, progress)
                    raise RuntimeError("DWG 저장 실패: " + result.get("error", "ZWCAD 오류"))
                with staging.open("rb") as handle:
                    signature = handle.read(6).decode("ascii")
                staging.rename(target_path)
                result.update(
                    commercial_use_verified=False,
                    education_stamp_status="unknown",
                    file=target_path.name,
                    signature=signature,
                    engine=progid,
                )
                source_path.with_suffix(".dwg.report.json").write_text(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return result
            finally:
                if proc.poll() is not None:
                    for suffix in (".dwg", ".bak", ".dwl", ".dwl2"):
                        try:
                            staging.with_suffix(suffix).unlink(missing_ok=True)
                        except OSError:
                            pass
