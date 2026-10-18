import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
CANDIDATE_FILE = PROJECT_DIR / 'candidate_model_v02.json'
DECISIONS_FILE = PROJECT_DIR / 'review_decisions.json'
OUTPUT_CANDIDATE_FILE = PROJECT_DIR / 'candidate_model_reviewed.json'
OUTPUT_GEOMETRY_FILE = PROJECT_DIR / 'geometry_from_pdf_reviewed.json'
REPORT_FILE = PROJECT_DIR / 'output' / 'review_handoff_report.json'
PROVISIONAL_TYPES = {'stairway', 'column'}


def load_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def manual_state(candidate, decisions):
    d = decisions.get(candidate['id'])
    if d == 'approve':
        return 'approved'
    if d == 'reject':
        return 'rejected'
    return 'unchanged'


def include_candidate(candidate, state):
    if state == 'approved':
        return True
    if state == 'rejected':
        return False
    if candidate['status'] == 'auto_accept':
        return True
    return candidate['status'] == 'review_recommended' and candidate['type'] in PROVISIONAL_TYPES


def main():
    if not CANDIDATE_FILE.exists():
        raise FileNotFoundError(CANDIDATE_FILE)
    if not DECISIONS_FILE.exists():
        raise FileNotFoundError('review_decisions.json not found. Download it from review_overlay_v01.html and place it in the project folder.')

    model = load_json(CANDIDATE_FILE)
    decision_doc = load_json(DECISIONS_FILE)
    decisions = decision_doc.get('decisions', {})
    invalid = {k: v for k, v in decisions.items() if v not in {'approve', 'reject'}}
    if invalid:
        raise ValueError(f'Unsupported review decisions: {invalid}')

    reviewed = json.loads(json.dumps(model))
    levels = {}
    areas, walls, columns, obstacles, vcs = [], [], [], [], []
    excluded, provisional, included = [], [], []
    area_key, wall_key, column_key, obstacle_key, vc_key = 1001, 1101, 1301, 1401, 2001

    for page in reviewed['pages']:
        for c in page['candidates']:
            state = manual_state(c, decisions)
            c['manual_decision'] = state
            include = include_candidate(c, state)
            ctype = c['type']

            if not include:
                if ctype not in {'scale', 'level'}:
                    excluded.append({'id': c['id'], 'type': ctype, 'manual_decision': state, 'status': c['status'], 'confidence': c['confidence']})
                continue

            included.append(c['id'])
            if state == 'unchanged' and c['status'] == 'review_recommended':
                provisional.append(c['id'])

            if ctype == 'level':
                lk = int(c['properties']['level_key'])
                levels[lk] = {'key': lk, 'name': 'Ground Floor' if lk == 1 else f'Level {lk}', 'z': float(c['properties']['z'])}
            elif ctype == 'area':
                areas.append({'key': area_key, 'name': f'Reviewed Area {area_key}', 'level_key': int(c['properties']['level_key']), 'polygon': c['geometry']['polygon']})
                area_key += 1
            elif ctype == 'wall':
                openings = [{'name': f'Reviewed Door D{i:02d}', 'center': op['center'], 'width': op['width']} for i, op in enumerate(c['properties'].get('openings', []), start=1)]
                walls.append({'key': wall_key, 'name': f'Reviewed Wall {wall_key}', 'level_key': int(c['properties']['level_key']), 'start': c['geometry']['start'], 'end': c['geometry']['end'], 'thickness': c['properties']['thickness'], 'height': c['properties'].get('height', 3.0), 'openings': openings})
                wall_key += 1
            elif ctype == 'column':
                p = c['properties']
                item = {'key': column_key, 'name': f'Reviewed Column {column_key}', 'level_key': int(p['level_key']), 'shape': p['shape'], 'center': c['geometry']['center'], 'height': p.get('height', 3.0)}
                if p['shape'] == 'circle':
                    item['diameter'] = p['diameter']
                else:
                    item.update({'width': p['width'], 'depth': p['depth'], 'rotation_deg': p.get('rotation_deg', 0.0)})
                columns.append(item)
                column_key += 1
            elif ctype == 'equipment':
                obstacles.append({'key': obstacle_key, 'name': f'Reviewed Equipment {obstacle_key}', 'type': 'equipment', 'level_key': int(c['properties']['level_key']), 'height': c['properties'].get('height', 1.2), 'z_offset': 0.0, 'polygon': c['geometry']['polygon']})
                obstacle_key += 1
            elif ctype == 'stairway':
                p = c['properties']
                vcs.append({'key': vc_key, 'name': f'Reviewed Stair {vc_key}', 'type': 'stairway', 'start_level': int(p['start_level']), 'end_level': int(p['end_level']), 'start_z_offset': 0.0, 'end_z_offset': 0.0, 'polygon': c['geometry']['polygon'], 'steps': int(p.get('steps', 24)), 'thickness': float(p.get('thickness', 0.2)), 'show_balustrade': bool(p.get('show_balustrade', True))})
                vc_key += 1

    for page in reviewed['pages']:
        lk = int(page['level_key'])
        levels.setdefault(lk, {'key': lk, 'name': 'Ground Floor' if lk == 1 else f'Level {lk}', 'z': (lk - 1) * 4.0})

    geometry = {
        'project': {'name': 'PDF Reviewed Viswalk Model v0.1', 'units': 'm', 'source': model['source_file']},
        'defaults': {'wall_height': 3.0, 'column_height': 3.0, 'obstacle_height': 1.2, 'z_offset': 0.0, 'level_key': 1},
        'transform': {'scale': 1.0, 'rotation_deg': 0.0, 'origin': [0.0, 0.0]},
        'levels': [levels[k] for k in sorted(levels)],
        'areas': areas,
        'walls': walls,
        'columns': columns,
        'obstacles': obstacles,
        'vertical_connections': vcs,
    }

    report = {
        'source_candidate_file': str(CANDIDATE_FILE),
        'source_decisions_file': str(DECISIONS_FILE),
        'manual_decision_count': len(decisions),
        'included_candidate_ids': included,
        'provisional_candidate_ids': provisional,
        'excluded': excluded,
        'geometry_counts': {'levels': len(geometry['levels']), 'areas': len(areas), 'walls': len(walls), 'columns': len(columns), 'obstacles': len(obstacles), 'vertical_connections': len(vcs)},
        'status': 'REVIEW' if provisional else 'PASS',
    }

    OUTPUT_CANDIDATE_FILE.write_text(json.dumps(reviewed, indent=2, ensure_ascii=False), encoding='utf-8')
    OUTPUT_GEOMETRY_FILE.write_text(json.dumps(geometry, indent=2, ensure_ascii=False), encoding='utf-8')
    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')

    print('Visual Review Handoff v0.1')
    print('=' * 60)
    print('Manual decisions:', report['manual_decision_count'])
    for k, v in report['geometry_counts'].items():
        print(f'{k:<22}: {v}')
    print('Provisional candidates:', len(provisional))
    print('Excluded candidates:', len(excluded))
    print('Status:', report['status'])
    print('Geometry for Vissim:')
    print(OUTPUT_GEOMETRY_FILE)
    print('Report:')
    print(REPORT_FILE)


if __name__ == '__main__':
    main()
