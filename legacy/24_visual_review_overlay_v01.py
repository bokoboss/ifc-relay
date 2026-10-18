import base64
import json
from pathlib import Path
from string import Template
import fitz

PROJECT_DIR = Path(__file__).resolve().parent
PDF_FILE = PROJECT_DIR / 'sample_floorplan_unstyled.pdf'
CANDIDATE_FILE = PROJECT_DIR / 'candidate_model_v02.json'
OUTPUT_HTML = PROJECT_DIR / 'review_overlay_v01.html'
ZOOM = 2.0

TYPE_STYLE = {
    'area': ('#1473e6', 'rgba(20,115,230,0.06)'),
    'wall': ('#00a36c', 'rgba(0,163,108,0.08)'),
    'column': ('#7b61ff', 'rgba(123,97,255,0.10)'),
    'equipment': ('#d17a00', 'rgba(209,122,0,0.10)'),
    'stairway': ('#e55353', 'rgba(229,83,83,0.10)'),
    'unknown_rectangle': ('#6b7280', 'rgba(107,114,128,0.10)'),
}


def model_to_px(x_m, y_m, page_data):
    x0, y0, x1, y1 = page_data['floor_bbox_pdf']
    mpp = float(page_data['meters_per_pdf_point'])
    x_pdf = x0 + float(x_m) / mpp
    y_pdf = y1 - float(y_m) / mpp
    return x_pdf * ZOOM, y_pdf * ZOOM


def polygon_px(points, page_data):
    vals = []
    for x, y in points:
        px, py = model_to_px(x, y, page_data)
        vals.append(f'{px:.2f},{py:.2f}')
    return ' '.join(vals)


def candidate_svg(c, page_data):
    ctype = c['type']
    if ctype not in TYPE_STYLE:
        return ''

    stroke, fill = TYPE_STYLE[ctype]
    g = c.get('geometry', {})
    p = c.get('properties', {})
    cid = c['id']
    conf = float(c['confidence'])
    parts = []
    label_xy = None

    if ctype == 'area' and g.get('polygon'):
        pts = polygon_px(g['polygon'], page_data)
        parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="2" stroke-dasharray="9 5"/>')
        xs = [q[0] for q in g['polygon']]
        ys = [q[1] for q in g['polygon']]
        label_xy = model_to_px(min(xs), max(ys), page_data)

    elif ctype == 'wall' and g.get('start') and g.get('end'):
        x1, y1 = model_to_px(*g['start'], page_data)
        x2, y2 = model_to_px(*g['end'], page_data)
        mpp = float(page_data['meters_per_pdf_point'])
        sw = max(4.0, float(p.get('thickness', 0.2)) / mpp * ZOOM)
        parts.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{stroke}" stroke-opacity="0.55" stroke-width="{sw:.2f}"/>')
        for opening in p.get('openings', []):
            cx, cy = model_to_px(opening['center'][0], opening['center'][1], page_data)
            r = max(8.0, float(opening['width']) / mpp * ZOOM / 4.0)
            parts.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="rgba(255,255,255,0.85)" stroke="#e11d48" stroke-width="3"/>')
        label_xy = (x1, y1)

    elif ctype == 'column' and g.get('center'):
        cx, cy = model_to_px(*g['center'], page_data)
        mpp = float(page_data['meters_per_pdf_point'])
        if p.get('shape') == 'circle':
            r = float(p.get('diameter', 0.6)) / mpp * ZOOM / 2.0
            parts.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{fill}" stroke="{stroke}" stroke-width="3"/>')
        else:
            w = float(p.get('width', 0.6)) / mpp * ZOOM
            h = float(p.get('depth', 0.6)) / mpp * ZOOM
            angle = -float(p.get('rotation_deg', 0.0))
            parts.append(f'<rect x="{cx-w/2:.2f}" y="{cy-h/2:.2f}" width="{w:.2f}" height="{h:.2f}" fill="{fill}" stroke="{stroke}" stroke-width="3" transform="rotate({angle:.2f} {cx:.2f} {cy:.2f})"/>')
        label_xy = (cx, cy)

    elif ctype in {'equipment', 'stairway', 'unknown_rectangle'} and g.get('polygon'):
        pts = polygon_px(g['polygon'], page_data)
        parts.append(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="3"/>')
        xs = [q[0] for q in g['polygon']]
        ys = [q[1] for q in g['polygon']]
        label_xy = model_to_px(min(xs), max(ys), page_data)

    if not parts:
        return ''

    lx, ly = label_xy
    ly -= 8
    label = f'{cid} {conf*100:.0f}%'
    box_w = max(90, len(label) * 7.2)
    parts.append(
        f'<g class="candidate-label"><rect x="{lx:.2f}" y="{ly-19:.2f}" rx="5" width="{box_w:.2f}" height="22" fill="rgba(17,24,39,0.88)"/>'
        f'<text x="{lx+6:.2f}" y="{ly-4:.2f}" fill="white" font-size="13" font-family="Arial">{label}</text></g>'
    )
    return f'<g class="candidate-shape" data-id="{cid}" data-type="{ctype}" onclick="selectCandidate(\'{cid}\')">{"".join(parts)}</g>'


def render_page(page):
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), alpha=False)
    b64 = base64.b64encode(pix.tobytes('png')).decode('ascii')
    return b64, pix.width, pix.height


def main():
    model = json.loads(CANDIDATE_FILE.read_text(encoding='utf-8'))
    doc = fitz.open(PDF_FILE)
    if len(doc) != len(model['pages']):
        raise ValueError('PDF page count does not match candidate model')

    candidate_index = {}
    rows = []
    page_sections = []

    for page_data in model['pages']:
        for c in page_data['candidates']:
            candidate_index[c['id']] = c
            cls = 'auto' if c['status'] == 'auto_accept' else ('review' if c['status'] == 'review_recommended' else 'required')
            rows.append(
                f'<button class="candidate-row {cls}" data-row-id="{c["id"]}" data-type="{c["type"]}" onclick="selectCandidate(\'{c["id"]}\')">'
                f'<div class="row-top"><strong>{c["id"]}</strong><span>{c["confidence"]*100:.0f}%</span></div>'
                f'<div class="row-bottom"><span>{c["type"]}</span><span>{c["status"]}</span></div></button>'
            )

    for i, page_data in enumerate(model['pages']):
        b64, width, height = render_page(doc[i])
        svg = ''.join(candidate_svg(c, page_data) for c in page_data['candidates'])
        page_sections.append(
            f'<section class="page-card" id="page-{page_data["page"]}">'
            f'<div class="page-header"><span>Page {page_data["page"]} · Level {page_data["level_key"]} · Scale 1:{page_data["scale_denominator"]:.0f}</span>'
            f'<span>{page_data["floor_size_m"][0]:.2f} × {page_data["floor_size_m"][1]:.2f} m</span></div>'
            f'<div class="page-stage" style="width:{width}px;height:{height}px">'
            f'<img class="page-image" src="data:image/png;base64,{b64}" width="{width}" height="{height}"/>'
            f'<svg class="overlay-svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">{svg}</svg>'
            f'</div></section>'
        )

    template = Template(r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Viswalk AI - Visual Review Overlay v0.1</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;background:#f3f4f6;color:#111827}.app{display:grid;grid-template-columns:300px minmax(0,1fr) 350px;height:100vh;overflow:hidden}.left,.right{background:white;overflow:auto}.left{border-right:1px solid #e5e7eb}.right{border-left:1px solid #e5e7eb}.panel-title{position:sticky;top:0;z-index:10;background:white;padding:16px;border-bottom:1px solid #e5e7eb}.panel-title h1{font-size:18px;margin:0 0 5px}.muted{font-size:12px;color:#6b7280}.candidate-list{padding:10px}.candidate-row{width:100%;text-align:left;background:white;border:1px solid #e5e7eb;border-radius:8px;padding:9px;margin-bottom:7px;cursor:pointer}.candidate-row.auto{border-left:5px solid #10b981}.candidate-row.review{border-left:5px solid #f59e0b}.candidate-row.required{border-left:5px solid #ef4444}.candidate-row.selected{border-color:#2563eb;box-shadow:0 0 0 2px rgba(37,99,235,.12)}.row-top,.row-bottom{display:flex;justify-content:space-between;gap:8px}.row-bottom{font-size:11px;color:#6b7280;margin-top:4px}.workspace{overflow:auto;padding:18px}.page-card{width:max-content;background:white;margin:0 auto 24px;padding:12px;border-radius:10px;box-shadow:0 4px 18px rgba(17,24,39,.1)}.page-header{display:flex;justify-content:space-between;font-size:12px;color:#4b5563;margin-bottom:8px}.page-stage{position:relative}.page-image,.overlay-svg{position:absolute;left:0;top:0}.candidate-shape{cursor:pointer}.candidate-shape:hover{filter:drop-shadow(0 0 5px rgba(37,99,235,.8))}.candidate-shape.selected{filter:drop-shadow(0 0 7px rgba(37,99,235,1))}.right-content{padding:16px}.card{border:1px solid #e5e7eb;border-radius:10px;padding:14px;margin-bottom:14px}.card h2{font-size:16px;margin:0 0 10px}.kv{display:grid;grid-template-columns:105px 1fr;gap:5px 8px;font-size:12px}.k{color:#6b7280}.evidence{font-size:12px;padding-left:18px}.decision-row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:7px}.action,.download{border:none;border-radius:7px;padding:9px;cursor:pointer;font-weight:700}.approve{background:#dcfce7;color:#166534}.reject{background:#fee2e2;color:#991b1b}.reset{background:#e5e7eb;color:#374151}.download{width:100%;background:#111827;color:white;padding:11px}.filters{display:flex;flex-wrap:wrap;gap:5px;margin-top:9px}.filters button{border:1px solid #d1d5db;background:white;border-radius:999px;padding:4px 7px;font-size:11px;cursor:pointer}.filters button.active{background:#111827;color:white}pre{white-space:pre-wrap;word-break:break-word;font-size:11px}
</style></head><body>
<div class="app"><aside class="left"><div class="panel-title"><h1>Detected Candidates</h1><div class="muted">Candidate + confidence review</div><div class="filters" id="filters"></div></div><div class="candidate-list">$ROWS</div></aside>
<main class="workspace">$PAGES</main>
<aside class="right"><div class="panel-title"><h1>Review</h1><div class="muted">Select a candidate</div></div><div class="right-content"><div class="card" id="empty">Click an overlay or item to inspect evidence and make a decision.</div><div id="detail" style="display:none"></div><button class="download" onclick="downloadDecisions()">Download review_decisions.json</button></div></aside></div>
<script>
const candidates=$CANDIDATES;
let selectedId=null;
let decisions=JSON.parse(localStorage.getItem('viswalkReviewDecisionsV01')||'{}');
function esc(v){return String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;')}
function types(){return [...new Set(Object.values(candidates).map(c=>c.type))].sort()}
function buildFilters(){const r=document.getElementById('filters');const all=document.createElement('button');all.textContent='All';all.className='active';all.onclick=()=>filter(null,all);r.appendChild(all);for(const t of types()){const b=document.createElement('button');b.textContent=t;b.onclick=()=>filter(t,b);r.appendChild(b)}}
function filter(t,b){document.querySelectorAll('#filters button').forEach(x=>x.classList.remove('active'));b.classList.add('active');document.querySelectorAll('.candidate-row').forEach(x=>x.style.display=(!t||x.dataset.type===t)?'':'none');document.querySelectorAll('.candidate-shape').forEach(x=>x.style.display=(!t||x.dataset.type===t)?'':'none')}
function selectCandidate(id){selectedId=id;document.querySelectorAll('.candidate-row').forEach(x=>x.classList.toggle('selected',x.dataset.rowId===id));document.querySelectorAll('.candidate-shape').forEach(x=>x.classList.toggle('selected',x.dataset.id===id));const c=candidates[id];if(!c)return;document.getElementById('empty').style.display='none';const d=document.getElementById('detail');d.style.display='block';const dec=decisions[id]||'unchanged';const ev=(c.evidence||[]).map(x=>'<li>'+esc(x)+'</li>').join('');d.innerHTML='<div class="card"><h2>'+esc(id)+'</h2><div class="kv"><div class="k">Type</div><div>'+esc(c.type)+'</div><div class="k">Confidence</div><div>'+Math.round(c.confidence*100)+'%</div><div class="k">Auto status</div><div>'+esc(c.status)+'</div><div class="k">Decision</div><div><strong>'+esc(dec)+'</strong></div></div></div><div class="card"><h2>Evidence</h2><ul class="evidence">'+(ev||'<li>No evidence</li>')+'</ul></div><div class="card"><h2>Decision</h2><div class="decision-row"><button class="action approve" onclick="setDecision(\'approve\')">Approve</button><button class="action reject" onclick="setDecision(\'reject\')">Reject</button><button class="action reset" onclick="setDecision(null)">Reset</button></div></div><div class="card"><h2>Properties</h2><pre>'+esc(JSON.stringify(c.properties||{},null,2))+'</pre></div>';}
function setDecision(v){if(!selectedId)return;if(v===null)delete decisions[selectedId];else decisions[selectedId]=v;localStorage.setItem('viswalkReviewDecisionsV01',JSON.stringify(decisions));selectCandidate(selectedId)}
function downloadDecisions(){const payload={schema_version:'0.1',source_candidate_file:'candidate_model_v02.json',generated_by:'Visual Review Overlay v0.1',decisions};const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='review_decisions.json';document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url)}
buildFilters();const init=Object.values(candidates).find(c=>c.status!=='auto_accept')||Object.values(candidates)[0];if(init)selectCandidate(init.id);
</script></body></html>''')

    html_text = template.substitute(
        ROWS=''.join(rows),
        PAGES=''.join(page_sections),
        CANDIDATES=json.dumps(candidate_index, ensure_ascii=False),
    )
    OUTPUT_HTML.write_text(html_text, encoding='utf-8')
    print('Visual Review Overlay v0.1')
    print('=' * 60)
    print('Candidates:', model['summary']['candidate_count'])
    print('Review items:', model['summary']['review_count'])
    print('Generated:')
    print(OUTPUT_HTML)
    print('Open this HTML in Chrome/Edge.')


if __name__ == '__main__':
    main()
