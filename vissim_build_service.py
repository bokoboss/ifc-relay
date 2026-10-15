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


_BUILD_LOCK = threading.Lock()


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
    adapter = app_dir / '40_vissim_build_adapter_v04.py'
    if not adapter.exists():
        raise FileNotFoundError(f'Build adapter missing: {adapter}')

    cmd = [
        sys.executable,
        str(adapter),
        '--project-root', str(project_root),
        '--input', str(semantic_path),
        '--validation-output', str(validation_path),
    ]
    if validate_only:
        cmd.append('--validate-only')
    else:
        if output_path is None or report_path is None:
            raise ValueError('Build output/report paths are required.')
        cmd += ['--output', str(output_path), '--report', str(report_path)]

    return subprocess.run(
        cmd,
        cwd=str(app_dir),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )


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
            tail = ((process.stderr or '') + '\n' + (process.stdout or ''))[-7000:].strip()
            raise RuntimeError(
                f'Vissim build failed with exit code {process.returncode}. '
                f'Log: {log_path}\n{tail}'
            )
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
