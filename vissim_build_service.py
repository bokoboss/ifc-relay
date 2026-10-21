from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from project_paths import BASE_NETWORK_FILE, engine_path


_BUILD_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Live build progress (read by GET /api/build/progress while a build runs).
# The adapter's output is read line by line; each line can move the stage on.
# ---------------------------------------------------------------------------
BUILD_STAGES = [
    ("validate", "ตรวจ Geometry"),
    ("connect", "เปิด Vissim"),
    ("base", "โหลดเครือข่ายตั้งต้น"),
    ("levels", "สร้างระดับชั้น"),
    ("areas", "สร้างพื้นที่เดิน"),
    ("obstacles", "สร้างสิ่งกีดขวาง"),
    ("vertical", "สร้างบันไดและทางลาด"),
    ("save", "บันทึกไฟล์ .inpx"),
]
_STAGE_INDEX = {key: i for i, (key, _) in enumerate(BUILD_STAGES)}
_progress_lock = threading.Lock()
_progress: dict[str, Any] = {"running": False}


def progress_start() -> None:
    with _progress_lock:
        _progress.clear()
        _progress.update({"running": True, "started": time.time(), "stage": "validate",
                          "done": 0, "total": 0, "totals": {}, "prog_id": None, "fallback": None,
                          "result": None, "message": ""})


def progress_finish(ok: bool, message: str = "") -> None:
    with _progress_lock:
        _progress.update({"running": False, "result": "success" if ok else "failed",
                          "message": message[:300], "finished": time.time()})


def _set_stage(state: dict[str, Any], stage: str, total_key: str | None = None) -> None:
    if _STAGE_INDEX[stage] < _STAGE_INDEX.get(state.get("stage"), 0):
        return
    state["stage"] = stage
    state["done"] = 0
    state["total"] = int(state.get("totals", {}).get(total_key, 0)) if total_key else 0


def apply_progress_line(state: dict[str, Any], line: str) -> None:
    """Move the build progress on from one line of adapter/engine output."""
    text = line.rstrip()
    stripped = text.strip()
    if stripped.startswith("{") and '"vissim_obstacles"' in stripped:
        try:
            summary = json.loads(stripped)
            state["totals"] = {"areas": summary.get("areas", 0), "obstacles": summary.get("vissim_obstacles", 0),
                               "vertical": summary.get("vertical_connections", 0)}
        except ValueError:
            pass
    elif stripped.startswith("Vissim COM ProgID:"):
        state["prog_id"] = stripped.split(":", 1)[1].split("(")[0].strip()
        _set_stage(state, "connect")
    elif stripped.startswith("VISSIM_FALLBACK:"):
        state["fallback"] = stripped
        state["stage"] = "connect"
    elif stripped.startswith("Connecting to Vissim"):
        _set_stage(state, "connect")
    elif stripped.startswith("Loading base network"):
        _set_stage(state, "base")
    elif stripped.startswith("Creating / configuring Levels"):
        _set_stage(state, "levels")
    elif stripped.startswith("Creating Areas"):
        _set_stage(state, "areas", "areas")
    elif stripped.startswith("Creating Obstacles"):
        _set_stage(state, "obstacles", "obstacles")
    elif stripped.startswith("Creating Vertical Connections"):
        _set_stage(state, "vertical", "vertical")
    elif stripped.startswith("Saving") or stripped.startswith("Vissim model saved"):
        _set_stage(state, "save")
    elif state.get("stage") in ("areas", "obstacles", "vertical") and text.startswith("  ") or \
            state.get("stage") == "vertical" and re.match(r"(STAIRWAY|RAMP) \d+:", stripped):
        state["done"] = int(state.get("done", 0)) + 1
    if stripped:
        state["last"] = stripped[:160]


def build_progress() -> dict[str, Any]:
    with _progress_lock:
        state = dict(_progress)
    if not state.get("started"):
        return {"running": False, "stages": BUILD_STAGES}
    end = state.get("finished") or time.time()
    state["elapsed_sec"] = round(end - state["started"], 1)
    state["stage_index"] = _STAGE_INDEX.get(state.get("stage"), 0)
    state["stages"] = BUILD_STAGES
    state.pop("totals", None)
    return state


def _safe_stem(name: str) -> str:
    stem = Path(name or 'model').stem
    stem = re.sub(r'[^A-Za-z0-9._ -]+', '_', stem).strip(' .')
    return stem or 'model'


def _run_adapter(
    app_dir: Path,
    project_root: Path,
    semantic_path: Path,
    validation_path: Path,
    *,
    output_path: Path | None = None,
    report_path: Path | None = None,
    validate_only: bool = False,
    timeout_sec: int = 240,
) -> subprocess.CompletedProcess[str]:
    adapter = app_dir / 'vissim_build_adapter.py'
    if not adapter.exists():
        raise FileNotFoundError(f'Build adapter missing: {adapter}')

    cmd = [
        sys.executable,
        str(adapter),
        '--project-root', str(project_root),
        '--input', str(semantic_path),
        '--validation-output', str(validation_path),
        '--engine', str(engine_path()),
        '--base-network', str(project_root / BASE_NETWORK_FILE),
    ]
    if validate_only:
        cmd.append('--validate-only')
    else:
        if output_path is None or report_path is None:
            raise ValueError('Build output/report paths are required.')
        cmd += ['--output', str(output_path), '--report', str(report_path)]

    if validate_only:
        return subprocess.run(
            cmd,
            cwd=str(app_dir),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
    return _run_streaming(cmd, app_dir, timeout_sec)


def _run_streaming(cmd: list[str], cwd: Path, timeout_sec: int) -> subprocess.CompletedProcess[str]:
    """Like subprocess.run(capture_output=True), but feeds each stdout line to the
    live build progress while the build runs."""
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", env=env)
    out_lines: list[str] = []
    err_chunks: list[str] = []

    def read_out() -> None:
        for line in proc.stdout:
            out_lines.append(line)
            with _progress_lock:
                apply_progress_line(_progress, line)

    def read_err() -> None:
        err_chunks.append(proc.stderr.read())

    readers = [threading.Thread(target=read_out, daemon=True), threading.Thread(target=read_err, daemon=True)]
    for t in readers:
        t.start()
    try:
        proc.wait(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        for t in readers:
            t.join(timeout=5)
        raise
    for t in readers:
        t.join(timeout=5)
    return subprocess.CompletedProcess(cmd, proc.returncode, "".join(out_lines), "".join(err_chunks))


def validate_engine_input(app_dir: Path, project_root: Path, semantic_path: Path) -> dict[str, Any]:
    runtime = app_dir / 'runtime' / 'validation'
    runtime.mkdir(parents=True, exist_ok=True)
    validation_path = runtime / 'latest_validation_v04.json'

    process = _run_adapter(
        app_dir,
        project_root,
        semantic_path,
        validation_path,
        validate_only=True,
        timeout_sec=120,
    )
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or '').strip()
        raise RuntimeError(f'Geometry Engine validation failed: {detail}')
    if not validation_path.exists():
        raise RuntimeError('Validation process completed without a validation report.')

    result = json.loads(validation_path.read_text(encoding='utf-8'))
    result['stdout'] = process.stdout[-5000:]
    return result




# Known Vissim COM failures -> what the engineer should do (Thai, shown in the app).
COM_ERROR_HINTS = {
    "-2146959355": "Vissim เปิดขึ้นมาแต่ไม่ตอบการเชื่อมต่อ (Server execution failed): ปิด Vissim ที่เปิดค้างอยู่ทุกหน้าต่าง "
                   "(ดูใน Task Manager ว่าไม่มี VISSIM*.exe), เปิดแอปและ Vissim แบบปกติทั้งคู่ (ไม่ใช่ Run as administrator) "
                   "และปิดหน้าต่างถามตอนเปิด Vissim (เช่นเลือก license) ด้วยการติ๊กไม่ต้องแสดงอีก",
    "-2147221005": "Windows ไม่พบ Vissim ใน COM (Invalid class string): เปิด Vissim (2025 หรือ 2026) แบบ Run as administrator หนึ่งครั้งเพื่อลงทะเบียน COM หรือกำหนด VBB_VISSIM_PROGID",
    "-2147221021": None,  # 'Operation unavailable' = no running instance; normal first attempt
}


def com_error_hint(text: str) -> str | None:
    for code, hint in COM_ERROR_HINTS.items():
        if hint and code in text:
            return hint
    return None


def running_vissim_processes() -> list[str]:
    """Names of running Vissim processes (Windows only; empty elsewhere or on error)."""
    if os.name != 'nt':
        return []
    try:
        out = subprocess.run(['tasklist', '/FO', 'CSV', '/NH'], capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return []
    names = []
    for line in out.splitlines():
        name = line.split('","')[0].strip('"')
        if name.lower().startswith('vissim'):
            names.append(name)
    return names


def build_preflight(base_network: Path) -> list[str]:
    """Problems that would make the COM build fail, in Thai, before Vissim is started."""
    problems = []
    if not base_network.exists():
        problems.append(
            f"ไม่พบไฟล์ base_empty.inpx ที่ {base_network} · เปิด Vissim (รุ่นที่จะใช้ build) > File > New > Save As "
            "ไปที่ตำแหน่งนี้ แล้วปิด Vissim ก่อนกดสร้างไฟล์อีกครั้ง"
        )
    if os.name == 'nt':
        from vissim_com import resolve_prog_id
        if resolve_prog_id()[0] is None:
            problems.append("ไม่พบ PTV Vissim 2025/2026 ที่ลงทะเบียน COM บนเครื่องนี้ · ติดตั้ง Vissim หรือเปิดแบบ Run as administrator หนึ่งครั้ง")
    running = running_vissim_processes()
    if running:
        problems.append(
            f"มี Vissim เปิดอยู่ ({', '.join(sorted(set(running)))}) · ปิด Vissim ทุกหน้าต่างก่อนสร้างไฟล์ "
            "เพราะแอปต้องเปิด Vissim ใหม่ผ่าน COM"
        )
    return problems

def _registered_choices() -> list[int]:
    try:
        from vissim_com import registered_releases
        return registered_releases()
    except Exception:
        return []


def build_failure_message(returncode: int, log_path: Path, stdout: str, stderr: str) -> str:
    """Error text for a failed build. The traceback (stderr) goes last and is never cut;
    stdout (which can hold thousands of validation warnings) is trimmed to its last lines."""
    out_lines = [line for line in stdout.strip().splitlines() if line.strip()]
    stdout_tail = '\n'.join(out_lines[-15:])
    err = stderr.strip()
    if len(err) > 6000:
        err = '...\n' + err[-6000:]
    hint = com_error_hint(stderr)
    tried = [line.split(':', 1)[1].split('(')[0].strip() for line in out_lines if line.startswith('Vissim COM ProgID:')]
    used = f'Vissim ที่ลองเชื่อมต่อ: {", ".join(tried)}\n' if tried else ''
    if tried and hint and len(tried) == 1 and len(_registered_choices()) > 1:
        used += 'เครื่องนี้มี Vissim หลายรุ่น · เลือกรุ่นอื่นได้ที่เมนู Engine แล้วลองสร้างไฟล์อีกครั้ง\n'
    return (
        (f'{hint}\n\n' if hint else '') + used
        + f'Vissim build failed with exit code {returncode}. Log: {log_path}\n'
        f'--- last output ---\n{stdout_tail}\n'
        f'--- error ---\n{err or "(no error text; see log)"}'
    )

def build_vissim_model(
    app_dir: Path,
    project_root: Path,
    semantic_path: Path,
    source_name: str,
) -> dict[str, Any]:
    if os.name != 'nt':
        raise RuntimeError('Vissim COM build is available only on Windows.')

    if not _BUILD_LOCK.acquire(blocking=False):
        raise RuntimeError('Another Vissim build is already running. Wait for it to finish.')

    started = time.time()
    try:
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        stem = _safe_stem(source_name)
        build_dir = project_root / 'output' / 'webapp_v04' / f'{stem}_{stamp}'
        build_dir.mkdir(parents=True, exist_ok=True)

        output_path = build_dir / f'{stem}_viswalk.inpx'
        report_path = build_dir / f'{stem}_geometry_engine_report.json'
        validation_path = build_dir / f'{stem}_validation_v04.json'
        log_path = build_dir / f'{stem}_build.log'

        process = _run_adapter(
            app_dir,
            project_root,
            semantic_path,
            validation_path,
            output_path=output_path,
            report_path=report_path,
            validate_only=False,
            timeout_sec=300,
        )

        log_text = (
            'COMMAND OUTPUT\n'
            + '=' * 72
            + '\nSTDOUT\n'
            + (process.stdout or '')
            + '\nSTDERR\n'
            + (process.stderr or '')
        )
        log_path.write_text(log_text, encoding='utf-8')

        if process.returncode != 0:
            raise RuntimeError(build_failure_message(process.returncode, log_path,
                                                     process.stdout or '', process.stderr or ''))
        if not output_path.exists():
            raise RuntimeError(f'Build completed without .inpx output. Log: {log_path}')
        if not validation_path.exists():
            raise RuntimeError(f'Build completed without validation report. Log: {log_path}')
        if not report_path.exists():
            raise RuntimeError(f'Build completed without Geometry Engine report. Log: {log_path}')

        validation = json.loads(validation_path.read_text(encoding='utf-8'))
        engine_report = json.loads(report_path.read_text(encoding='utf-8'))
        duration = round(time.time() - started, 2)

        return {
            'status': 'success',
            'duration_sec': duration,
            'output_path': str(output_path),
            'output_filename': output_path.name,
            'report_path': str(report_path),
            'validation_path': str(validation_path),
            'log_path': str(log_path),
            'validation': validation,
            'engine_summary': engine_report.get('summary', {}),
        }
    finally:
        _BUILD_LOCK.release()
