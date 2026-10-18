import base64
import json
from pathlib import Path

import fitz


PROJECT_DIR = Path(__file__).resolve().parent
PDF_FILE = PROJECT_DIR / "sample_floorplan_unstyled.pdf"
CANDIDATE_FILE = PROJECT_DIR / "candidate_model_v02.json"
OUTPUT_HTML = PROJECT_DIR / "review_workspace_v02.html"
ZOOM = 2.0


def render_page(page):
    pix = page.get_pixmap(matrix=fitz.Matrix(ZOOM, ZOOM), alpha=False)
    encoded = base64.b64encode(pix.tobytes("png")).decode("ascii")
    return encoded, pix.width, pix.height


def main():
    if not PDF_FILE.exists():
        raise FileNotFoundError(PDF_FILE)
    if not CANDIDATE_FILE.exists():
        raise FileNotFoundError(CANDIDATE_FILE)

    model = json.loads(CANDIDATE_FILE.read_text(encoding="utf-8"))
    doc = fitz.open(PDF_FILE)

    if len(doc) != len(model["pages"]):
        raise ValueError("PDF page count does not match candidate model")

    page_payload = []
    page_html = []

    for idx, page_data in enumerate(model["pages"]):
        b64, width, height = render_page(doc[idx])
        page_payload.append(
            {
                "page": int(page_data["page"]),
                "level_key": int(page_data["level_key"]),
                "scale_denominator": float(page_data["scale_denominator"]),
                "meters_per_pdf_point": float(page_data["meters_per_pdf_point"]),
                "floor_bbox_pdf": [float(x) for x in page_data["floor_bbox_pdf"]],
                "floor_size_m": [float(x) for x in page_data["floor_size_m"]],
                "width": width,
                "height": height,
            }
        )

        page_html.append(
            f'''<section class="page-card" id="page-card-{page_data['page']}">
              <div class="page-header">
                <span>Page {page_data['page']} · Level {page_data['level_key']} · Scale 1:{page_data['scale_denominator']:.0f}</span>
                <span>{page_data['floor_size_m'][0]:.2f} × {page_data['floor_size_m'][1]:.2f} m</span>
              </div>
              <div class="page-stage" style="width:{width}px;height:{height}px">
                <img class="page-image" src="data:image/png;base64,{b64}" width="{width}" height="{height}" alt="Page {page_data['page']}" />
                <svg class="overlay-svg" id="overlay-page-{page_data['page']}" viewBox="0 0 {width} {height}" width="{width}" height="{height}"></svg>
              </div>
            </section>'''
        )

    template = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>Viswalk AI - Review Workspace v0.2</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Inter,Arial,sans-serif;background:#eef1f5;color:#111827}.app{display:grid;grid-template-columns:300px minmax(0,1fr) 390px;height:100vh;overflow:hidden}.left,.right{background:#fff;overflow:auto}.left{border-right:1px solid #dfe3e8}.right{border-left:1px solid #dfe3e8}.panel-title{position:sticky;top:0;z-index:20;background:#fff;padding:15px;border-bottom:1px solid #e5e7eb}.panel-title h1{font-size:17px;margin:0 0 4px}.muted{font-size:11px;color:#6b7280}.toolbar{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}.toolbar button,.toolbar label{border:1px solid #d1d5db;background:#fff;border-radius:7px;padding:6px 8px;font-size:11px;cursor:pointer}.toolbar button.primary{background:#111827;color:white;border-color:#111827}.toolbar input[type=file]{display:none}.candidate-list{padding:9px}.candidate-row{width:100%;text-align:left;background:#fff;border:1px solid #e5e7eb;border-left:5px solid #9ca3af;border-radius:8px;padding:9px;margin-bottom:7px;cursor:pointer}.candidate-row.auto{border-left-color:#10b981}.candidate-row.review{border-left-color:#f59e0b}.candidate-row.required{border-left-color:#ef4444}.candidate-row.rejected{opacity:.52;text-decoration:line-through}.candidate-row.approved{box-shadow:inset 0 0 0 1px #10b981}.candidate-row.selected{border-color:#2563eb;box-shadow:0 0 0 2px rgba(37,99,235,.12)}.row-top,.row-bottom{display:flex;justify-content:space-between;gap:8px}.row-top{font-size:12px}.row-bottom{font-size:10px;color:#6b7280;margin-top:4px}.workspace{overflow:auto;padding:18px}.page-card{width:max-content;background:#fff;margin:0 auto 24px;padding:12px;border-radius:10px;box-shadow:0 4px 18px rgba(17,24,39,.1)}.page-header{display:flex;justify-content:space-between;gap:15px;font-size:11px;color:#4b5563;margin-bottom:8px}.page-stage{position:relative}.page-image,.overlay-svg{position:absolute;left:0;top:0}.overlay-svg{touch-action:none}.shape{cursor:pointer}.shape.selected{filter:drop-shadow(0 0 5px rgba(37,99,235,.95))}.handle{cursor:grab;stroke:#fff;stroke-width:2;fill:#2563eb}.handle.door{fill:#e11d48}.handle.column{fill:#7c3aed}.handle:active{cursor:grabbing}.label-bg{fill:rgba(17,24,39,.86)}.label-text{fill:white;font-size:12px;font-family:Arial,sans-serif}.right-content{padding:14px}.card{border:1px solid #e5e7eb;border-radius:9px;padding:12px;margin-bottom:12px}.card h2{font-size:14px;margin:0 0 9px}.kv{display:grid;grid-template-columns:110px 1fr;gap:5px 8px;font-size:11px}.k{color:#6b7280}.evidence{font-size:11px;padding-left:18px;margin:5px 0}.decision-row{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px}.action{border:none;border-radius:7px;padding:8px;cursor:pointer;font-weight:700}.approve{background:#dcfce7;color:#166534}.reject{background:#fee2e2;color:#991b1b}.reset{background:#e5e7eb;color:#374151}.field-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.field{display:flex;flex-direction:column;gap:3px}.field.full{grid-column:1/-1}.field label{font-size:10px;color:#6b7280}.field input,.field select{width:100%;border:1px solid #d1d5db;border-radius:6px;padding:6px;font-size:11px}.field input[type=checkbox]{width:auto}.section-note{font-size:10px;color:#6b7280;margin-top:6px}.filters{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}.filters button{border:1px solid #d1d5db;background:white;border-radius:999px;padding:4px 7px;font-size:10px;cursor:pointer}.filters button.active{background:#111827;color:white}.badge{display:inline-block;padding:3px 6px;border-radius:999px;background:#f3f4f6;font-size:10px}.warning{background:#fff7ed;border-color:#fdba74}.success{background:#ecfdf5;border-color:#6ee7b7}pre{white-space:pre-wrap;word-break:break-word;font-size:10px;margin:0}
</style>
</head>
<body>
<div class="app">
  <aside class="left">
    <div class="panel-title">
      <h1>Review Workspace v0.2</h1>
      <div class="muted">Drag handles or edit values in the inspector.</div>
      <div class="toolbar">
        <button class="primary" onclick="downloadWorkspace()">Export workspace state</button>
        <label>Load state<input id="stateFile" type="file" accept="application/json" onchange="loadWorkspaceFile(event)" /></label>
        <button onclick="resetWorkspace()">Reset all</button>
      </div>
      <div class="filters" id="filters"></div>
    </div>
    <div class="candidate-list" id="candidateList"></div>
  </aside>

  <main class="workspace">$PAGES</main>

  <aside class="right">
    <div class="panel-title">
      <h1>Inspector</h1>
      <div class="muted">Numeric edits update the overlay immediately.</div>
    </div>
    <div class="right-content">
      <div class="card" id="emptyDetail">Select a candidate.</div>
      <div id="detail" style="display:none"></div>
    </div>
  </aside>
</div>

<script>
const baseModel=$MODEL;
const pageMeta=$PAGEMETA;
const storageKey='viswalkReviewWorkspaceV02';
let workspace=loadStoredWorkspace();
let selectedId=null;
let activeFilter=null;
let dragState=null;

const styleMap={
  area:{stroke:'#1473e6',fill:'rgba(20,115,230,.05)'},
  wall:{stroke:'#00a36c',fill:'rgba(0,163,108,.08)'},
  column:{stroke:'#7b61ff',fill:'rgba(123,97,255,.10)'},
  equipment:{stroke:'#d17a00',fill:'rgba(209,122,0,.10)'},
  stairway:{stroke:'#e55353',fill:'rgba(229,83,83,.10)'},
  unknown_rectangle:{stroke:'#6b7280',fill:'rgba(107,114,128,.10)'},
  scale:{stroke:'#374151',fill:'rgba(55,65,81,.05)'},
  level:{stroke:'#374151',fill:'rgba(55,65,81,.05)'}
};

function deepClone(v){return JSON.parse(JSON.stringify(v));}
function esc(v){return String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');}
function loadStoredWorkspace(){
  try{const raw=localStorage.getItem(storageKey);if(raw){const parsed=JSON.parse(raw);if(parsed.schema_version==='0.2')return parsed;}}catch(e){}
  return {schema_version:'0.2',source_candidate_file:'candidate_model_v02.json',candidates:{},decisions:{}};
}
function persist(){localStorage.setItem(storageKey,JSON.stringify(workspace));}
function allCandidates(){const arr=[];for(const p of baseModel.pages){for(const base of p.candidates){arr.push(getCandidate(base.id));}}return arr;}
function baseCandidateById(id){for(const p of baseModel.pages){for(const c of p.candidates){if(c.id===id)return c;}}return null;}
function getCandidate(id){const base=baseCandidateById(id);if(!base)return null;const override=workspace.candidates[id];return override?deepClone(override):deepClone(base);}
function saveCandidate(c){workspace.candidates[c.id]=deepClone(c);persist();}
function pageForCandidate(c){return pageMeta.find(p=>p.page===Number(c.source.page));}
function m2px(x,y,page){const [x0,y0,x1,y1]=page.floor_bbox_pdf;const mpp=page.meters_per_pdf_point;return [(x0+x/mpp)*$ZOOM,(y1-y/mpp)*$ZOOM];}
function px2m(px,py,page){const [x0,y0,x1,y1]=page.floor_bbox_pdf;const mpp=page.meters_per_pdf_point;return [(px/$ZOOM-x0)*mpp,(y1-py/$ZOOM)*mpp];}
function svgEl(name,attrs={}){const el=document.createElementNS('http://www.w3.org/2000/svg',name);for(const [k,v] of Object.entries(attrs)){el.setAttribute(k,String(v));}return el;}
function decisionFor(id){return workspace.decisions[id]||'unchanged';}
function setDecision(v){if(!selectedId)return;if(v==='unchanged')delete workspace.decisions[selectedId];else workspace.decisions[selectedId]=v;persist();renderSidebar();renderInspector();renderAllPages();}
function uniqueTypes(){return [...new Set(allCandidates().map(c=>c.type))].sort();}
function buildFilters(){const root=document.getElementById('filters');root.innerHTML='';const types=[null,...uniqueTypes()];for(const t of types){const b=document.createElement('button');b.textContent=t||'All';b.classList.toggle('active',activeFilter===t);b.onclick=()=>{activeFilter=t;buildFilters();renderSidebar();renderAllPages();};root.appendChild(b);}}
function rowClass(c){const d=decisionFor(c.id);let cls='candidate-row ';cls+=c.status==='auto_accept'?'auto':(c.status==='review_recommended'?'review':'required');if(d==='approve')cls+=' approved';if(d==='reject')cls+=' rejected';if(c.id===selectedId)cls+=' selected';return cls;}
function renderSidebar(){const root=document.getElementById('candidateList');root.innerHTML='';for(const c of allCandidates()){if(activeFilter&&c.type!==activeFilter)continue;const b=document.createElement('button');b.className=rowClass(c);b.dataset.id=c.id;b.onclick=()=>selectCandidate(c.id);const d=decisionFor(c.id);b.innerHTML=`<div class="row-top"><strong>${esc(c.id)}</strong><span>${Math.round(c.confidence*100)}%</span></div><div class="row-bottom"><span>${esc(c.type)}</span><span>${esc(d==='unchanged'?c.status:d)}</span></div>`;root.appendChild(b);}}
function labelGroup(c,x,y){const g=svgEl('g');const text=`${c.id} ${Math.round(c.confidence*100)}%`;const w=Math.max(88,text.length*6.6);const r=svgEl('rect',{x,y:y-18,width:w,height:20,rx:5,class:'label-bg'});const t=svgEl('text',{x:x+5,y:y-4,class:'label-text'});t.textContent=text;g.append(r,t);return g;}
function addHandle(group,x,y,cid,kind,index=null,cls=''){const h=svgEl('circle',{cx:x,cy:y,r:6,class:`handle ${cls}`, 'data-candidate':cid,'data-handle':kind});if(index!==null)h.setAttribute('data-index',index);h.addEventListener('pointerdown',startDrag);group.appendChild(h);}
function renderCandidate(svg,c,page){if(activeFilter&&c.type!==activeFilter)return;if(['scale','level'].includes(c.type))return;const style=styleMap[c.type]||styleMap.unknown_rectangle;const g=svgEl('g',{class:`shape${c.id===selectedId?' selected':''}`,'data-id':c.id});g.addEventListener('click',e=>{if(e.target.classList.contains('handle'))return;selectCandidate(c.id);});const geom=c.geometry||{},p=c.properties||{};let labelX=14,labelY=24;
  if(c.type==='area'&&geom.polygon){const pts=geom.polygon.map(q=>m2px(q[0],q[1],page).join(',')).join(' ');g.appendChild(svgEl('polygon',{points:pts,fill:style.fill,stroke:style.stroke,'stroke-width':2,'stroke-dasharray':'8 5'}));const px=m2px(Math.min(...geom.polygon.map(q=>q[0])),Math.max(...geom.polygon.map(q=>q[1])),page);[labelX,labelY]=px;}
  else if(c.type==='wall'&&geom.start&&geom.end){const a=m2px(...geom.start,page),b=m2px(...geom.end,page);const sw=Math.max(4,Number(p.thickness||.2)/page.meters_per_pdf_point*$ZOOM);g.appendChild(svgEl('line',{x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:style.stroke,'stroke-opacity':.55,'stroke-width':sw}));addHandle(g,a[0],a[1],c.id,'wall_start');addHandle(g,b[0],b[1],c.id,'wall_end');for(let i=0;i<(p.openings||[]).length;i++){const op=p.openings[i];const q=m2px(op.center[0],op.center[1],page);g.appendChild(svgEl('circle',{cx:q[0],cy:q[1],r:Math.max(8,Number(op.width||1)/page.meters_per_pdf_point*$ZOOM/5),fill:'rgba(255,255,255,.88)',stroke:'#e11d48','stroke-width':3}));addHandle(g,q[0],q[1],c.id,'door_center',i,'door');} [labelX,labelY]=a;}
  else if(c.type==='column'&&geom.center){const q=m2px(...geom.center,page);if(p.shape==='circle'){const r=Number(p.diameter||.6)/page.meters_per_pdf_point*$ZOOM/2;g.appendChild(svgEl('circle',{cx:q[0],cy:q[1],r,fill:style.fill,stroke:style.stroke,'stroke-width':3}));}else{const w=Number(p.width||.6)/page.meters_per_pdf_point*$ZOOM,h=Number(p.depth||.6)/page.meters_per_pdf_point*$ZOOM;const rect=svgEl('rect',{x:q[0]-w/2,y:q[1]-h/2,width:w,height:h,fill:style.fill,stroke:style.stroke,'stroke-width':3,transform:`rotate(${-Number(p.rotation_deg||0)} ${q[0]} ${q[1]})`});g.appendChild(rect);}addHandle(g,q[0],q[1],c.id,'column_center',null,'column');[labelX,labelY]=q;}
  else if(['equipment','stairway','unknown_rectangle'].includes(c.type)&&geom.polygon){const pts=geom.polygon.map(q=>m2px(q[0],q[1],page).join(',')).join(' ');g.appendChild(svgEl('polygon',{points:pts,fill:style.fill,stroke:style.stroke,'stroke-width':3}));const xs=geom.polygon.map(q=>q[0]),ys=geom.polygon.map(q=>q[1]);[labelX,labelY]=m2px(Math.min(...xs),Math.max(...ys),page);}
  else{return;}
  g.appendChild(labelGroup(c,labelX,labelY-7));svg.appendChild(g);
}
function renderAllPages(){for(const p of pageMeta){const svg=document.getElementById(`overlay-page-${p.page}`);svg.innerHTML='';for(const c of allCandidates().filter(x=>Number(x.source.page)===p.page)){if(decisionFor(c.id)==='reject')continue;renderCandidate(svg,c,p);}}}
function selectCandidate(id){selectedId=id;const c=getCandidate(id);const page=pageForCandidate(c);const card=document.getElementById(`page-card-${page.page}`);if(card)card.scrollIntoView({block:'nearest'});renderSidebar();renderInspector();renderAllPages();}
function field(label,value,path,opts={}){const wrap=document.createElement('div');wrap.className='field'+(opts.full?' full':'');const lab=document.createElement('label');lab.textContent=label;let input;if(opts.select){input=document.createElement('select');for(const option of opts.select){const o=document.createElement('option');o.value=option.value;o.textContent=option.label;o.selected=String(value)===String(option.value);input.appendChild(o);}}else{input=document.createElement('input');input.type=opts.type||'number';if(input.type==='number'){input.step=opts.step||'0.01';}if(input.type==='checkbox'){input.checked=Boolean(value);}else{input.value=value??'';}}input.dataset.path=path;input.addEventListener('change',onInspectorChange);wrap.append(lab,input);return wrap;}
function valueAtPath(obj,path){return path.split('.').reduce((a,k)=>a?.[k],obj);}
function setAtPath(obj,path,value){const parts=path.split('.');let ref=obj;for(let i=0;i<parts.length-1;i++){const k=parts[i];if(!(k in ref))ref[k]={};ref=ref[k];}ref[parts.at(-1)]=value;}
function onInspectorChange(e){if(!selectedId)return;let c=getCandidate(selectedId);const path=e.target.dataset.path;if(!path)return;let value;if(e.target.type==='checkbox')value=e.target.checked;else if(e.target.tagName==='SELECT')value=e.target.value;else if(e.target.type==='number')value=Number(e.target.value);else value=e.target.value;
  if(path==='__convert_type__'){convertCandidate(c,value);}else{setAtPath(c,path,value);}saveCandidate(c);renderSidebar();renderInspector();renderAllPages();}
function bboxFromPolygon(poly){const xs=poly.map(p=>p[0]),ys=poly.map(p=>p[1]);return {minx:Math.min(...xs),maxx:Math.max(...xs),miny:Math.min(...ys),maxy:Math.max(...ys)};}
function convertCandidate(c,newType){if(c.type!=='unknown_rectangle')return;if(newType==='unknown_rectangle')return;const poly=c.geometry.polygon||[];const b=bboxFromPolygon(poly);if(newType==='equipment'){c.type='equipment';c.properties={level_key:c.properties.level_key||1,height:1.2};}
  else if(newType==='column'){c.type='column';c.geometry={center:[(b.minx+b.maxx)/2,(b.miny+b.maxy)/2]};c.properties={level_key:c.properties.level_key||1,shape:'rectangle',width:b.maxx-b.minx,depth:b.maxy-b.miny,rotation_deg:0,height:3.0};}
}
function renderInspector(){const empty=document.getElementById('emptyDetail'),detail=document.getElementById('detail');if(!selectedId){empty.style.display='block';detail.style.display='none';return;}const c=getCandidate(selectedId);empty.style.display='none';detail.style.display='block';detail.innerHTML='';const summary=document.createElement('div');summary.className='card';summary.innerHTML=`<h2>${esc(c.id)}</h2><div class="kv"><div class="k">Type</div><div>${esc(c.type)}</div><div class="k">Confidence</div><div>${Math.round(c.confidence*100)}%</div><div class="k">Auto status</div><div>${esc(c.status)}</div><div class="k">Decision</div><div><strong>${esc(decisionFor(c.id))}</strong></div></div>`;detail.appendChild(summary);
  const dec=document.createElement('div');dec.className='card';dec.innerHTML='<h2>Decision</h2><div class="decision-row"><button class="action approve" onclick="setDecision(\'approve\')">Approve</button><button class="action reject" onclick="setDecision(\'reject\')">Reject</button><button class="action reset" onclick="setDecision(\'unchanged\')">Reset</button></div>';detail.appendChild(dec);
  if(c.type==='unknown_rectangle'){const conv=document.createElement('div');conv.className='card warning';conv.innerHTML='<h2>Resolve semantic type</h2><div class="field-grid"></div><div class="section-note">Convert this ambiguous rectangle before approving it.</div>';conv.querySelector('.field-grid').appendChild(field('Convert to','unknown_rectangle','__convert_type__',{full:true,select:[{value:'unknown_rectangle',label:'Keep Unknown'},{value:'equipment',label:'Equipment'},{value:'column',label:'Column'}]}));detail.appendChild(conv);}
  const edit=document.createElement('div');edit.className='card';edit.innerHTML='<h2>Editable properties</h2><div class="field-grid" id="editGrid"></div>';const grid=edit.querySelector('#editGrid');
  if(c.type==='wall'){grid.append(field('Start X',c.geometry.start[0],'geometry.start.0'),field('Start Y',c.geometry.start[1],'geometry.start.1'),field('End X',c.geometry.end[0],'geometry.end.0'),field('End Y',c.geometry.end[1],'geometry.end.1'),field('Thickness',c.properties.thickness,'properties.thickness'),field('Height',c.properties.height,'properties.height'),field('Level',c.properties.level_key,'properties.level_key',{step:'1'}));for(let i=0;i<(c.properties.openings||[]).length;i++){const op=c.properties.openings[i];grid.append(field(`Door ${i+1} X`,op.center[0],`properties.openings.${i}.center.0`),field(`Door ${i+1} Y`,op.center[1],`properties.openings.${i}.center.1`),field(`Door ${i+1} width`,op.width,`properties.openings.${i}.width`,{full:true}));}}
  else if(c.type==='column'){grid.append(field('Center X',c.geometry.center[0],'geometry.center.0'),field('Center Y',c.geometry.center[1],'geometry.center.1'),field('Level',c.properties.level_key,'properties.level_key',{step:'1'}),field('Height',c.properties.height,'properties.height'));if(c.properties.shape==='circle')grid.append(field('Diameter',c.properties.diameter,'properties.diameter',{full:true}));else grid.append(field('Width',c.properties.width,'properties.width'),field('Depth',c.properties.depth,'properties.depth'),field('Rotation',c.properties.rotation_deg||0,'properties.rotation_deg',{full:true}));}
  else if(c.type==='stairway'){grid.append(field('Start level',c.properties.start_level,'properties.start_level',{step:'1'}),field('End level',c.properties.end_level,'properties.end_level',{step:'1'}),field('Steps',c.properties.steps||24,'properties.steps',{step:'1'}),field('Thickness',c.properties.thickness||.2,'properties.thickness'));}
  else if(c.type==='equipment'){grid.append(field('Level',c.properties.level_key,'properties.level_key',{step:'1'}),field('Height',c.properties.height||1.2,'properties.height'));}
  else if(c.type==='level'){grid.append(field('Level key',c.properties.level_key,'properties.level_key',{step:'1'}),field('Elevation Z',c.properties.z,'properties.z'));}
  else if(c.type==='area'){grid.append(field('Level',c.properties.level_key,'properties.level_key',{step:'1',full:true}));}
  else if(c.type==='scale'){grid.append(field('Scale denominator',c.properties.denominator,'properties.denominator',{full:true}));}
  if(grid.children.length===0){grid.innerHTML='<div class="section-note">No editable fields for this candidate type.</div>';}detail.appendChild(edit);
  const evidence=document.createElement('div');evidence.className='card';evidence.innerHTML='<h2>Evidence</h2><ul class="evidence">'+(c.evidence||[]).map(x=>`<li>${esc(x)}</li>`).join('')+'</ul>';detail.appendChild(evidence);
}
function startDrag(e){e.stopPropagation();const h=e.currentTarget;selectedId=h.dataset.candidate;dragState={id:selectedId,kind:h.dataset.handle,index:h.dataset.index!==undefined?Number(h.dataset.index):null,page:pageForCandidate(getCandidate(selectedId))};h.setPointerCapture(e.pointerId);h.addEventListener('pointermove',dragMove);h.addEventListener('pointerup',dragEnd,{once:true});selectCandidate(selectedId);}
function dragMove(e){if(!dragState)return;const svg=document.getElementById(`overlay-page-${dragState.page.page}`);const pt=svg.createSVGPoint();pt.x=e.clientX;pt.y=e.clientY;const loc=pt.matrixTransform(svg.getScreenCTM().inverse());const [x,y]=px2m(loc.x,loc.y,dragState.page);const c=getCandidate(dragState.id);if(dragState.kind==='wall_start')c.geometry.start=[x,y];else if(dragState.kind==='wall_end')c.geometry.end=[x,y];else if(dragState.kind==='column_center')c.geometry.center=[x,y];else if(dragState.kind==='door_center')c.properties.openings[dragState.index].center=[x,y];saveCandidate(c);renderInspector();renderAllPages();}
function dragEnd(e){e.currentTarget.removeEventListener('pointermove',dragMove);dragState=null;}
function downloadWorkspace(){const payload=deepClone(workspace);payload.generated_by='Review Workspace v0.2';payload.source_candidate_file='candidate_model_v02.json';payload.exported_at=new Date().toISOString();const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='review_workspace_state.json';document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);}
function loadWorkspaceFile(e){const file=e.target.files?.[0];if(!file)return;const reader=new FileReader();reader.onload=()=>{try{const parsed=JSON.parse(reader.result);if(parsed.schema_version!=='0.2')throw new Error('Unsupported workspace schema');workspace={schema_version:'0.2',source_candidate_file:'candidate_model_v02.json',candidates:parsed.candidates||{},decisions:parsed.decisions||{}};persist();selectedId=null;renderEverything();alert('Workspace state loaded.');}catch(err){alert('Could not load state: '+err.message);}};reader.readAsText(file);}
function resetWorkspace(){if(!confirm('Reset all edits and review decisions?'))return;workspace={schema_version:'0.2',source_candidate_file:'candidate_model_v02.json',candidates:{},decisions:{}};localStorage.removeItem(storageKey);selectedId=null;renderEverything();}
function renderEverything(){buildFilters();renderSidebar();renderAllPages();renderInspector();}
renderEverything();const initial=allCandidates().find(c=>c.status!=='auto_accept')||allCandidates()[0];if(initial)selectCandidate(initial.id);
</script>
</body>
</html>'''

    html_text = (
        template
        .replace('$PAGES', ''.join(page_html))
        .replace('$MODEL', json.dumps(model, ensure_ascii=False))
        .replace('$PAGEMETA', json.dumps(page_payload, ensure_ascii=False))
        .replace('$ZOOM', str(ZOOM))
    )

    OUTPUT_HTML.write_text(html_text, encoding="utf-8")

    print("Review Workspace v0.2")
    print("=" * 60)
    print("Candidates:", model["summary"]["candidate_count"])
    print("Pages:", len(model["pages"]))
    print("Generated:")
    print(OUTPUT_HTML)
    print("Open the HTML in Chrome or Edge.")


if __name__ == "__main__":
    main()
