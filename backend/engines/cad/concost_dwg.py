"""Use the user's installed ZWCAD via its COM API. AGPL-3.0-or-later."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import time
import base64


class Cancelled(RuntimeError):
    pass


def installed_zwcad():
    import winreg
    versions = []
    with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "") as key:
        for index in range(winreg.QueryInfoKey(key)[0]):
            name = winreg.EnumKey(key, index)
            if name.startswith("ZWCAD.Application.") and name.rsplit(".", 1)[1].isdigit():
                versions.append(name)
    return sorted(versions, key=lambda x: int(x.rsplit(".", 1)[1]), reverse=True)


def convert_dwg(source, progid, progress=print, cancelled=lambda: False, timeout=1200):
    source = Path(source).resolve()
    target = source.with_suffix(".dwg")
    if target.exists():
        raise FileExistsError(f"기존 DWG는 덮어쓰지 않습니다: {target.name}")
    if progid not in installed_zwcad():
        raise RuntimeError("선택한 ZWCAD가 등록되어 있지 않습니다. ZWCAD 설치와 실행을 확인하세요.")
    if cancelled():
        raise Cancelled("DWG 저장 전 취소됨 · DXF는 보존됩니다.")
    progress("DWG 단계 · ZWCAD 연결 / 저장 / 다시 열기 검증 중")
    # Staging lives next to the DXF, so relative IMAGE paths keep their meaning.
    with tempfile.TemporaryDirectory(prefix="dwg-job-") as temp:
        jobpath = Path(temp) / "job.json"
        resultpath = Path(temp) / "result.json"
        import uuid
        staging = source.parent / f".dwg-{uuid.uuid4().hex}.dwg"
        jobpath.write_text(json.dumps(dict(source=str(source), target=str(staging),
            progid=progid, result=str(resultpath)), ensure_ascii=False), encoding="utf-8")
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        with (Path(temp) / "process.log").open("wb") as log:
            script = Path(__file__).with_name("zwcad_save.ps1").read_text(encoding="utf-8")
            command = "& {\n" + script + "\n} '" + str(jobpath).replace("'", "''") + "'"
            proc = subprocess.Popen([str(powershell), "-NoProfile", "-NonInteractive", "-EncodedCommand",
                base64.b64encode(command.encode("utf-16-le")).decode("ascii")],
                stdout=log, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            started = time.monotonic()
            try:
                while proc.poll() is None:
                    if time.monotonic() - started > timeout:
                        proc.kill()
                        proc.wait()
                        raise TimeoutError("ZWCAD 응답 시간 초과. DXF는 보존됩니다. ZWCAD 창에서 대화상자를 확인하세요.")
                    time.sleep(0.2)
                if cancelled():
                    raise Cancelled("DWG 작업 구간 종료 후 취소됨 · DXF는 보존됩니다.")
                result = json.loads(resultpath.read_text(encoding="utf-8-sig")) if resultpath.exists() else {}
                if proc.returncode or not result.get("success"):
                    raise RuntimeError("DWG 저장 실패 · DXF는 보존됩니다. " + result.get("error", "ZWCAD 설치·라이선스·열린 대화상자를 확인하세요."))
                with staging.open("rb") as handle:
                    signature = handle.read(6).decode("ascii")
                if signature not in {"AC1015", "AC1018", "AC1021", "AC1024", "AC1027", "AC1032"}:
                    raise RuntimeError("저장 파일의 DWG 형식을 확인할 수 없습니다.")
                if result["source_entities"] != result["saved_entities"]:
                    raise RuntimeError("DWG 재열기 객체 수가 DXF와 다릅니다. DXF를 확인하세요.")
                staging.rename(target)  # Windows rename refuses an existing destination.
                result.update(commercial_use_verified=False,education_stamp_status="unknown",file=target.name, signature=signature, engine=progid)
                source.with_suffix(".dwg.report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                progress(f"DWG 저장·재열기 확인 완료: {target.name} ({result['saved_entities']:,}개 객체)")
                return result
            finally:
                if proc.poll() is not None:
                    for suffix in (".dwg", ".bak", ".dwl", ".dwl2"):
                        try:
                            staging.with_suffix(suffix).unlink(missing_ok=True)
                        except OSError:
                            pass
