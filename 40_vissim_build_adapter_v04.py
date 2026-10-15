from __future__ import annotations

import argparse
import builtins
import importlib.util
import json
import platform
import sys
import types
from pathlib import Path
from typing import Any


def _ensure_validation_import_compatibility(validate_only: bool) -> None:
    if not validate_only:
        return
    try:
        import win32com.client  # noqa: F401
    except Exception:
        # Geometry validation does not use COM. This shim lets the proven engine
        # module load on non-Windows QA machines while keeping real builds Windows-only.
        win32com = types.ModuleType('win32com')
        client = types.ModuleType('win32com.client')
        win32com.client = client
        sys.modules['win32com'] = win32com
        sys.modules['win32com.client'] = client


def load_engine(engine_path: Path, validate_only: bool):
    _ensure_validation_import_compatibility(validate_only)
    spec = importlib.util.spec_from_file_location('viswalk_geometry_engine_v03_runtime', engine_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'Cannot load engine module: {engine_path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def classify_issues(engine: Any, warnings: list[dict[str, Any]], levels, areas, obstacles, vertical):
    obstacle_by_key = {int(x['key']): x for x in obstacles}
    area_levels = {int(x['level_key']) for x in areas}
    obstacle_levels = {int(x['level_key']) for x in obstacles}
    vertical_levels = set()
    for x in vertical:
        vertical_levels.add(int(x['start_level']))
        vertical_levels.add(int(x['end_level']))

    issues = []
    for warning in warnings:
        issue = dict(warning)
        wtype = warning.get('type')
        severity = 'warning'
        rationale = None

        if wtype == 'level_without_walkable_area':
            level_key = int(warning['level_key'])
            if level_key not in obstacle_levels and level_key not in vertical_levels:
                severity = 'info'
                rationale = 'Level has no active simulation geometry; commonly a roof/service-only storey.'

        elif wtype == 'obstacle_outside_walkable':
            record = obstacle_by_key.get(int(warning.get('key', -1)))
            if record:
                name = str(record.get('name', '')).lower()
                if record.get('type') == 'wall' and ('outside wall' in name or 'exterior' in name):
                    severity = 'info'
                    rationale = 'Exterior boundary wall outside the walkable floor envelope is expected.'

        elif wtype in {
            'vertical_connection_not_on_start_area',
            'vertical_connection_not_on_end_area',
            'obstacle_overlap',
        }:
            severity = 'warning'

        issue['severity'] = severity
        if rationale:
            issue['rationale'] = rationale
        issues.append(issue)

    counts = {'error': 0, 'warning': 0, 'info': 0}
    for issue in issues:
        sev = issue['severity']
        counts[sev] = counts.get(sev, 0) + 1

    return issues, counts


def validate_geometry(engine: Any, input_path: Path) -> dict[str, Any]:
    data = engine.load_json(input_path)
    units = data.get('project', {}).get('units', 'm')
    if units != 'm':
        raise ValueError("Geometry Engine v0.3 requires project.units = 'm'.")

    levels, areas, obstacles, vertical = engine.build_geometry_model(data)
    raw_warnings = engine.validate_model(levels, areas, obstacles, vertical)
    vissim_obstacles = engine.prepare_vissim_obstacles(obstacles)
    issues, severity_counts = classify_issues(
        engine, raw_warnings, levels, areas, obstacles, vertical
    )

    return {
        'status': 'pass',
        'build_allowed': severity_counts['error'] == 0,
        'engine_version': getattr(engine, 'ENGINE_VERSION', '0.3'),
        'summary': {
            'levels': len(levels),
            'areas': len(areas),
            'semantic_obstacles': len(obstacles),
            'vissim_obstacles': len(vissim_obstacles),
            'vertical_connections': len(vertical),
        },
        'severity_counts': severity_counts,
        'issues': issues,
        'raw_warning_count': len(raw_warnings),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Web-safe adapter for Geometry Engine v0.3')
    parser.add_argument('--project-root', required=True)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output')
    parser.add_argument('--report')
    parser.add_argument('--validation-output', required=True)
    parser.add_argument('--validate-only', action='store_true')
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    input_path = Path(args.input).resolve()
    engine_path = project_root / '05_geometry_engine_v03.py'
    base_network = project_root / 'base_empty.inpx'
    validation_output = Path(args.validation_output).resolve()
    validation_output.parent.mkdir(parents=True, exist_ok=True)

    if not engine_path.exists():
        raise FileNotFoundError(f'Geometry Engine v0.3 not found: {engine_path}')
    if not input_path.exists():
        raise FileNotFoundError(f'Engine input not found: {input_path}')
    if not base_network.exists():
        raise FileNotFoundError(f'Base Vissim network not found: {base_network}')

    engine = load_engine(engine_path, args.validate_only)
    validation = validate_geometry(engine, input_path)
    validation_output.write_text(
        json.dumps(validation, indent=2, ensure_ascii=False), encoding='utf-8'
    )

    print('Validation summary:')
    print(json.dumps(validation['summary'], ensure_ascii=False))
    print('Severity counts:')
    print(json.dumps(validation['severity_counts'], ensure_ascii=False))

    if args.validate_only:
        print('VALIDATION_ONLY: PASS')
        return 0

    if platform.system().lower() != 'windows':
        raise RuntimeError('Vissim COM build requires Windows.')

    if not args.output or not args.report:
        raise ValueError('--output and --report are required for a Vissim build.')

    output_path = Path(args.output).resolve()
    report_path = Path(args.report).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)

    # Repoint only runtime globals. The original engine file and geometry_v03.json
    # remain untouched.
    engine.SOURCE_FILE = base_network
    engine.JSON_FILE = input_path
    engine.OUTPUT_DIR = output_path.parent
    engine.OUTPUT_FILE = output_path
    engine.REPORT_FILE = report_path

    original_input = builtins.input
    builtins.input = lambda prompt='': (print(f'{prompt}[auto-close]'), '')[1]
    try:
        engine.main()
    finally:
        builtins.input = original_input

    if not output_path.exists():
        raise RuntimeError(f'Vissim build returned without output file: {output_path}')
    if not report_path.exists():
        raise RuntimeError(f'Geometry Engine report missing: {report_path}')

    print('BUILD_OUTPUT:', output_path)
    print('BUILD_REPORT:', report_path)
    print('BUILD_ADAPTER: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
