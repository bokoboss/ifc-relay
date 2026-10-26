const fileInput = document.getElementById('fileInput');
const uploadBtn = document.getElementById('uploadBtn');
const analyzeBtn = document.getElementById('analyzeBtn');
const load3dBtn = document.getElementById('load3dBtn');
const generateSemanticBtn = document.getElementById('generateSemanticBtn');
const exportEngineBtn = document.getElementById('exportEngineBtn');
const downloadSemanticTopBtn = document.getElementById('downloadSemanticTopBtn');
const downloadEngineTopBtn = document.getElementById('downloadEngineTopBtn');
const validateBtn = document.getElementById('validateBtn');
const buildViswalkBtn = document.getElementById('buildViswalkBtn');
const downloadInpxTopBtn = document.getElementById('downloadInpxTopBtn');
const downloadInpxBtn = document.getElementById('downloadInpxBtn');
const downloadBuildReportBtn = document.getElementById('downloadBuildReportBtn');
const downloadValidationBtn = document.getElementById('downloadValidationBtn');
const downloadBuildLogBtn = document.getElementById('downloadBuildLogBtn');
const openBuildFolderBtn = document.getElementById('openBuildFolderBtn');
const resetBtn = document.getElementById('resetBtn');
const messageText = document.getElementById('messageText');
const geometryLoadMode = document.getElementById('geometryLoadMode');
const geometryStoreySelect = document.getElementById('geometryStoreySelect');
const appendStoreyCheck = document.getElementById('appendStoreyCheck');

let selectedFile = null;
let currentAudit = null;
let currentGeometry = null;
let currentSemantic = null;
let currentValidation = null;
let currentBuild = null;
let selectionState = { mode: 'auto', overrides: {} };
let selectedElement = null;
let activeStoreys = new Set();
let activeCategories = new Set();
let viewerRuntimeError = null;

window.addEventListener('error', event => {
  const source = String(event.filename || '');
  const message = String(event.message || 'Unknown browser error');
  if (source.includes('app3d.js') || source.includes('three') || message.toLowerCase().includes('webgl')) {
    viewerRuntimeError = message;
    setMessage(`ตัวแสดงผล 3D ผิดพลาด: ${message}`);
    const status = document.getElementById('viewerStatus');
    if (status) status.textContent = `ตัวแสดงผล 3D ผิดพลาด: ${message}`;
  }
});

window.addEventListener('unhandledrejection', event => {
  const message = event.reason?.message || String(event.reason || 'Unknown module error');
  viewerRuntimeError = message;
  setMessage(`โหลดโมดูล 3D ไม่สำเร็จ: ${message}`);
  const status = document.getElementById('viewerStatus');
  if (status) status.textContent = `โหลดโมดูล 3D ไม่สำเร็จ: ${message}`;
});

function setMessage(text) {
  messageText.textContent = text;
  messageText.title = text;          // the bar shows one line; hover for all of it
}

// ---------------------------------------------------------------------------
// Review dock (UX-01): lists live in a bottom dock with its own scroll, so the
// viewport never leaves the screen. Tabs keep the original section ids.
// ---------------------------------------------------------------------------
const dock = (() => {
  const root = document.getElementById('reviewDock');
  const body = document.getElementById('dockBody');
  const toggle = document.getElementById('dockToggle');
  const tabs = [...root.querySelectorAll('.dock-tab')];
  const panels = [...root.querySelectorAll('.dock-panel')];
  const store = {
    get(key) { try { return localStorage.getItem(`vbb.dock.${key}`); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(`vbb.dock.${key}`, value); } catch { /* private mode */ } },
  };
  let active = store.get('tab') || 'checks';

  function setOpen(open) {
    root.dataset.open = open ? 'true' : 'false';
    toggle.setAttribute('aria-expanded', String(open));
    toggle.querySelector('.dock-toggle-text').textContent = open ? 'ย่อ' : 'ขยาย';
    store.set('open', open ? '1' : '0');
  }
  // Four task tabs (GUI-01). Older names still work: they open the tab that
  // holds that list, filtered to it.
  const ALIAS = {
    checks: ['issues', 'checks'], choices: ['issues', 'choices'], stairs: ['issues', 'stairs'],
    model: ['details'], ifc: ['details'], engine: ['build'],
  };
  const issuesPanel = root.querySelector('.dock-panel[data-panel="issues"]');
  function setFilter(filter) {
    issuesPanel.dataset.filter = filter;
    issuesPanel.querySelectorAll('.issue-filter-btn').forEach(b => b.classList.toggle('active', b.dataset.filter === filter));
  }
  issuesPanel.querySelectorAll('.issue-filter-btn').forEach(b => b.addEventListener('click', () => setFilter(b.dataset.filter)));
  setFilter('all');

  function select(name, { open = true } = {}) {
    if (ALIAS[name]) {
      const [tab, filter] = ALIAS[name];
      if (filter) setFilter(filter);
      name = tab;
    }
    if (!panels.some(p => p.dataset.panel === name)) return;
    active = name;
    for (const t of tabs) t.setAttribute('aria-selected', String(t.dataset.tab === name));
    for (const p of panels) p.classList.toggle('active', p.dataset.panel === name);
    store.set('tab', name);
    if (open) setOpen(true);
  }
  tabs.forEach(t => t.addEventListener('click', () => {
    if (t.dataset.tab === active && root.dataset.open === 'true') setOpen(false);
    else select(t.dataset.tab);
  }));
  root.querySelector('.dock-tabs').addEventListener('keydown', event => {
    if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return;
    const i = tabs.findIndex(t => t.dataset.tab === active);
    const next = tabs[(i + (event.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
    select(next.dataset.tab);
    next.focus();
  });
  toggle.addEventListener('click', () => setOpen(root.dataset.open !== 'true'));

  // Height: drag the top edge (or arrow keys on it); remembered per browser.
  const handle = document.getElementById('dockResize');
  const setHeight = px => {
    const h = Math.round(Math.min(Math.max(px, 120), window.innerHeight * 0.7));
    root.style.setProperty('--dock-h', `${h}px`);
    store.set('height', String(h));
  };
  const saved = Number(store.get('height'));
  if (saved) setHeight(saved);
  handle.addEventListener('pointerdown', event => {
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    const startY = event.clientY;
    const startH = body.getBoundingClientRect().height;
    const move = e => setHeight(startH + (startY - e.clientY));
    const up = () => { handle.removeEventListener('pointermove', move); handle.removeEventListener('pointerup', up); };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', up);
  });
  handle.addEventListener('keydown', event => {
    const h = body.getBoundingClientRect().height;
    if (event.key === 'ArrowUp') { setHeight(h + 24); event.preventDefault(); }
    if (event.key === 'ArrowDown') { setHeight(h - 24); event.preventDefault(); }
  });

  // Tab counts follow what the panels actually contain.
  const checksCount = () => document.getElementById('gateSection').classList.contains('hidden') ? 0
    : document.querySelectorAll('#gateList .gate-row.check, #gateList .gate-row.block').length;
  const GROUP_COUNTS = {
    checks: checksCount,
    choices: () => document.querySelectorAll('#openingCandidateList .opening-row, #offLevelList .check-row').length,
    stairs: () => document.querySelectorAll('#verticalList .vertical-row').length,
  };
  const COUNTS = {
    issues: () => [checksCount(), document.querySelectorAll('#gateList .gate-row.block').length ? 'block' : 'warn'],
    edits: () => [document.querySelectorAll('#editsList .edit-row').length,
                  document.querySelector('#editsReview.needs-review') ? 'warn' : ''],
    build: () => [Number(document.getElementById('buildErrors')?.textContent) || 0, 'block'],
    details: () => [0, ''],
  };
  let pending = false;
  function updateCounts() {
    pending = false;
    for (const [name, fn] of Object.entries(COUNTS)) {
      const el = root.querySelector(`.dock-count[data-count="${name}"]`);
      const [n, tone] = fn();
      el.textContent = n ? String(n) : '';
      el.className = `dock-count${n && tone ? ` ${tone}` : ''}`;
    }
    for (const [group, fn] of Object.entries(GROUP_COUNTS)) {
      const n = fn();
      const el = issuesPanel.querySelector(`[data-filter-count="${group}"]`);
      if (el) el.textContent = n ? String(n) : '';
      const btn = issuesPanel.querySelector(`.issue-filter-btn[data-filter="${group}"]`);
      if (btn) {
        btn.disabled = !n;
        if (!n && issuesPanel.dataset.filter === group) setFilter('all');
      }
    }
  }
  new MutationObserver(() => {
    if (!pending) { pending = true; requestAnimationFrame(updateCounts); }
  }).observe(body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['class'] });

  select(active, { open: false });
  setOpen(store.get('open') === '1');
  updateCounts();
  return { select, setOpen };
})();

// Narrow screens: the inspector floats over the viewer; it can be closed and
// comes back with the next selection.
(() => {
  const layout = document.getElementById('explorerSection');
  document.getElementById('inspectorCloseBtn').addEventListener('click', () => layout.classList.add('inspector-dismissed'));
  new MutationObserver(() => layout.classList.remove('inspector-dismissed'))
    .observe(document.getElementById('selectedGuid'), { childList: true, characterData: true, subtree: true });
})();

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

function formatBytes(bytes) {
  const n = Number(bytes || 0);
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  // Any change on the server can make the pedestrian model stale or move the
  // workflow on: re-read the project state once things settle.
  if ((options.method || 'GET') !== 'GET' && !url.startsWith('/api/project')) scheduleWorkflowRefresh();
  if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
  return payload;
}

// ---------------------------------------------------------------------------
// Workflow state (UX-05, UX-09): the four command buttons carry their step
// state (done / stale / next), and a banner in the viewport says when the
// pedestrian model on screen does not include the latest changes.
// ---------------------------------------------------------------------------
let workflowTimer = null;
function scheduleWorkflowRefresh() {
  clearTimeout(workflowTimer);
  workflowTimer = setTimeout(refreshWorkflowState, 250);
}

async function refreshWorkflowState() {
  let state;
  try { state = await (await fetch('/api/project')).json(); } catch { return; }
  const semantic = state.semantic || {};
  const build = state.build || {};
  const ready = semantic.status === 'ready';
  const stale = ready && !!semantic.stale;
  const current = ready && !stale;
  const steps = {
    file: state.upload ? 'done' : 'next',
    prepare: !state.upload ? 'idle' : stale ? 'stale' : current ? 'done' : 'next',
    validate: !current ? 'idle' : ['validated', 'success'].includes(build.status) ? 'done' : 'next',
    build: !current || !['validated', 'success'].includes(build.status) ? 'idle' : build.status === 'success' ? 'done' : 'next',
  };
  const targets = { file: document.querySelector('.file-picker'), prepare: generateSemanticBtn, validate: validateBtn, build: buildViswalkBtn };
  const words = { done: 'เสร็จแล้ว', stale: 'ต้องทำใหม่', next: 'ขั้นถัดไป', idle: '' };
  for (const [step, el] of Object.entries(targets)) {
    if (!el) continue;
    el.dataset.step = steps[step];
    el.setAttribute('aria-description', words[steps[step]]);
  }
  document.getElementById('staleBanner').classList.toggle('hidden', !stale);
}

document.getElementById('staleRegenerateBtn').addEventListener('click', () => generateSemanticBtn.click());
setTimeout(refreshWorkflowState, 0);

// Left-panel search over the loaded IFC objects.
(() => {
  const input = document.getElementById('modelSearch');
  const list = document.getElementById('modelSearchResults');
  function render() {
    const v = viewer();
    const hits = v?.searchSource ? v.searchSource(input.value) : [];
    list.innerHTML = '';
    list.classList.toggle('hidden', input.value.trim().length < 2);
    if (input.value.trim().length < 2) return;
    if (!hits.length) {
      const li = document.createElement('li');
      li.className = 'search-empty';
      li.textContent = 'ไม่พบในส่วนที่โหลดแล้ว';
      list.appendChild(li);
      return;
    }
    for (const hit of hits) {
      const li = document.createElement('li');
      const button = document.createElement('button');
      button.type = 'button';
      button.setAttribute('role', 'option');
      button.title = `${hit.name} · ${hit.guid}`;
      const name = document.createElement('span');
      name.className = 'search-name';
      name.textContent = hit.name || hit.guid;
      const meta = document.createElement('span');
      meta.className = 'search-meta';
      meta.textContent = [hit.type, hit.storey].filter(Boolean).join(' · ');
      button.append(name, meta);
      button.addEventListener('click', () => {
        document.getElementById('sourceModeBtn').click();
        v.showSource(hit.guid);
        setMessage(`แสดง ${hit.name || hit.guid} ในโมเดลต้นฉบับ`);
      });
      li.appendChild(button);
      list.appendChild(li);
    }
  }
  let t = null;
  input.addEventListener('input', () => { clearTimeout(t); t = setTimeout(render, 120); });
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter') list.querySelector('button')?.click();
    if (event.key === 'Escape') { input.value = ''; render(); }
  });
})();

function viewer() {
  return window.IFCViewer || null;
}

function setExportReady(ready) {
  downloadSemanticTopBtn.disabled = !ready;
  downloadEngineTopBtn.disabled = !ready;
  validateBtn.disabled = !ready;
  // Build is refused only when the Engine cannot build the model.
  buildViswalkBtn.disabled = !ready || !(currentGate && currentGate.passed);
  if (!ready) {
    currentGate = null;
    document.getElementById('gateSection')?.classList.add('hidden');
  }
  if (!ready) setBuildOutputReady(false);
}

// The pedestrian model no longer matches the selection: block validate/build and
// exports until it is regenerated (the server enforces the same rule).
function markSemanticStale() {
  setExportReady(false);
  document.getElementById('stepSemantic')?.classList.remove('done');
}

function setBuildOutputReady(ready) {
  downloadInpxTopBtn.disabled = !ready;
  downloadInpxBtn.disabled = !ready;
  downloadBuildReportBtn.disabled = !ready;
  downloadValidationBtn.disabled = !ready;
  downloadBuildLogBtn.disabled = !ready;
  openBuildFolderBtn.disabled = !ready;
  if (!ready) document.getElementById('stepBuild').classList.remove('done');
}

function startDownload(url) {
  const a = document.createElement('a');
  a.href = url;
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

let viewerModulePromise = null;

async function ensureViewerModule() {
  if (viewer()) return viewer();

  if (!viewerModulePromise) {
    viewerRuntimeError = null;
    viewerModulePromise = import('/static/app3d.js?v=041')
      .then(() => {
        if (!window.IFCViewer) {
          throw new Error('app3d.js loaded but window.IFCViewer was not created.');
        }
        return window.IFCViewer;
      })
      .catch(error => {
        const message = error?.message || String(error);
        viewerRuntimeError = message;
        viewerModulePromise = null;
        setMessage(`โหลดโมดูล 3D ไม่สำเร็จ: ${message}`);
        const status = document.getElementById('viewerStatus');
        if (status) status.textContent = `โหลดโมดูล 3D ไม่สำเร็จ: ${message}`;
        throw error;
      });
  }

  return viewerModulePromise;
}

async function waitForViewer() {
  try {
    const v = await ensureViewerModule();
    if (!v) throw new Error('3D viewer module returned no viewer instance.');
    return v;
  } catch (error) {
    const message = error?.message || String(error);
    throw new Error(`3D engine failed to initialize: ${message}`);
  }
}

function effectiveStatus(item) {
  return selectionState.overrides?.[item.global_id] || item.recommendation || 'review';
}

function updateSelectionSummary() {
  if (!currentGeometry) return;
  const counts = { include: 0, review: 0, exclude: 0 };
  for (const item of currentGeometry.elements || []) {
    const status = effectiveStatus(item);
    if (status in counts) counts[status] += 1;
  }
  document.getElementById('effectiveInclude').textContent = counts.include;
  document.getElementById('effectiveReview').textContent = counts.review;
  document.getElementById('effectiveExclude').textContent = counts.exclude;
}

function applyViewerFilters() {
  viewer()?.setFilters([...activeStoreys], [...activeCategories]);
}

function mergeGeometryPayload(existing, incoming, append) {
  if (!append || !existing) return incoming;

  const byGuid = new Map();
  for (const item of existing.elements || []) {
    if (item.global_id) byGuid.set(item.global_id, item);
  }
  for (const item of incoming.elements || []) {
    if (item.global_id) byGuid.set(item.global_id, item);
  }

  const elements = [...byGuid.values()];
  const storeys = {};
  const categories = {};
  const simulationRoles = {};
  let triangleCount = 0;
  let vertexCount = 0;

  for (const item of elements) {
    const storey = item.storey_name || 'Unassigned';
    storeys[storey] = (storeys[storey] || 0) + 1;
    categories[item.ifc_type] = (categories[item.ifc_type] || 0) + 1;
    const role = item.simulation_role || 'review';
    simulationRoles[role] = (simulationRoles[role] || 0) + 1;
    triangleCount += Math.floor((item.indices?.length || 0) / 3);
    vertexCount += Math.floor((item.vertices?.length || 0) / 3);
  }

  return {
    ...incoming,
    element_count: elements.length,
    triangle_count: triangleCount,
    vertex_count: vertexCount,
    mesh_failures: [
      ...(existing.mesh_failures || []),
      ...(incoming.mesh_failures || []),
    ],
    storeys,
    categories,
    simulation_roles: simulationRoles,
    elements,
  };
}

function geometryRequestFromControls() {
  const value = geometryLoadMode?.value || 'simulation_all';
  const isFull = value.startsWith('full_');
  const isStorey = value.endsWith('_storey');
  const selectedStorey = Number(geometryStoreySelect?.value || 0);
  const storeyIds = isStorey && Number.isFinite(selectedStorey) && selectedStorey > 0
    ? [selectedStorey]
    : [];
  return {
    mode: isFull ? 'full' : 'simulation_relevant',
    storey_ids: storeyIds,
    append: !!appendStoreyCheck?.checked && isStorey,
    // Open the model with everything except review-rule elements (proxies,
    // furniture...), which can take minutes to tessellate; they follow in the background.
    tier: isFull ? 'all' : 'core',
  };
}

function updateLargeLoadControlState() {
  const value = geometryLoadMode?.value || 'simulation_all';
  const storeyMode = value.endsWith('_storey');
  if (geometryStoreySelect) geometryStoreySelect.disabled = !storeyMode;
  if (appendStoreyCheck) appendStoreyCheck.disabled = !storeyMode;
}

geometryLoadMode?.addEventListener('change', updateLargeLoadControlState);

// Choosing a file opens it straight away (import -> audit -> 3D), like a BIM viewer.
fileInput.addEventListener('change', () => {
  selectedFile = fileInput.files?.[0] || null;
  // Do not replace the current project banner until import is confirmed.
  if (selectedFile) openSelectedFile();
});

uploadBtn.addEventListener('click', () => openSelectedFile());

async function decidePendingImport(pending) {
  const dialog = document.getElementById('importConfirm');
  const oldFile = pending.source_file || 'ไม่ทราบชื่อ';
  document.getElementById('importConfirmFiles').textContent =
    `จาก: ${oldFile} → ไฟล์ใหม่: ${pending.destination_file}`;
  document.getElementById('importConfirmEdits').textContent =
    `รูปทรงที่แก้ไขเอง ${pending.manual_edit_count} รายการ · ระดับ: ${pending.affected_levels.join(', ') || 'ไม่มี'}`;

  const identity = pending.identity || { status: 'unverified', reasons: [] };
  const labels = { verified: 'ตรวจยืนยันว่าโครงการและระบบพิกัดตรงกัน',
                   mismatch: 'ข้อมูลโครงการ/หน่วย/ระบบพิกัดต่างกัน',
                   unverified: 'ยังตรวจยืนยันระบบพิกัดไม่ได้ครบ' };
  document.getElementById('importConfirmIdentity').textContent =
    `การเปรียบเทียบ IFC: ${labels[identity.status] || identity.status}`;
  document.getElementById('importConfirmSpatial').textContent =
    `${(identity.reasons || []).join(' · ') || 'ตรวจหน่วยและระบบพิกัดเท่าที่ IFC ระบุ'} · ` +
    'ระบบจะไม่ย้ายหรือแปลงพิกัดรูปทรงให้อัตโนมัติ';

  const carry = document.getElementById('importConfirmCarry');
  const risk = document.getElementById('importConfirmRisk');
  const riskRow = document.getElementById('importConfirmRiskRow');
  const go = document.getElementById('importConfirmGo');
  carry.checked = false;
  carry.disabled = !pending.manual_edit_count || identity.status === 'mismatch';
  risk.checked = false;
  riskRow.classList.toggle('hidden', identity.status !== 'unverified');
  const update = () => {
    go.disabled = carry.checked && identity.status === 'unverified' && !risk.checked;
  };
  carry.onchange = update;
  risk.onchange = update;
  update();

  const choice = await new Promise(resolve => {
    const finish = action => {
      dialog.removeEventListener('cancel', onEscape);
      dialog.close();
      resolve({ action, carry: carry.checked, risk: risk.checked });
    };
    const onEscape = event => { event.preventDefault(); finish('cancel'); };
    dialog.addEventListener('cancel', onEscape);
    document.getElementById('importConfirmCancel').onclick = () => finish('cancel');
    go.onclick = () => finish('confirm');
    dialog.showModal();
  });
  const data = {
    pending_token: pending.pending_token, expected_sha256: pending.sha256,
    carry_manual_edits: choice.carry, acknowledge_unverified: choice.risk,
  };
  if (choice.action === 'cancel') {
    await api('/api/import/cancel', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    });
    return null;
  }
  return api('/api/import/confirm', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  });
}

async function openSelectedFile() {
  if (!selectedFile) return;
  uploadBtn.disabled = true;
  setMessage('กำลังอัปโหลด IFC เพื่อเตรียมการยืนยัน...');
  try {
    const form = new FormData();
    form.append('file', selectedFile);
    form.append('carry_selection', document.getElementById('carrySelectionCheck')?.checked ? 'true' : 'false');
    let result = await api('/api/import', { method: 'POST', body: form });
    if (result.status === 'pending') {
      result = await decidePendingImport(result);
      if (!result) {
        setMessage('ยกเลิกการเปิดไฟล์ใหม่ · โครงการเดิมยังอยู่');
        return;
      }
    }
    geometryLoadSeq += 1; // Only invalidate the existing viewer after confirmation.
    document.getElementById('fileMeta').textContent =
      `${result.upload.original_name} · ${formatBytes(result.upload.size_bytes)} · นำเข้าแล้ว`;
    analyzeBtn.disabled = false;
    load3dBtn.disabled = true;
    generateSemanticBtn.disabled = true;
    currentAudit = null;
    currentGeometry = null;
    currentSemantic = null;
    if (geometryStoreySelect) geometryStoreySelect.innerHTML = '';
    document.getElementById('largeModelSection')?.classList.add('hidden');
    setMessage('ยืนยันการนำเข้าแล้ว · กำลังตรวจ IFC...');
    if (result.upload?.extension === '.ifc') {
      const audit = await runAnalyze();
      if (audit) {
        const loaded = await runLoad3d();
        if (loaded) {
          const large = audit.large_model?.recommended_load_mode === 'simulation_storey';
          setMessage(large
            ? 'IFC ขนาดใหญ่: โหลดชั้นแรกที่มี Geometry แล้ว · เลือกชั้นอื่นหรือเพิ่มชั้นได้จากแผงโหลดโมเดล'
            : 'เปิดโมเดลแล้ว · ตรวจการคัดเลือกองค์ประกอบ แล้วกด "เตรียมโมเดลคนเดิน"');
        }
      }
    } else {
      await runAnalyze();
    }
  } catch (error) {
    setMessage(`นำเข้าไฟล์ไม่สำเร็จ: ${error.message}`);
  } finally {
    uploadBtn.disabled = false;
    fileInput.value = '';
  }
}

async function runAnalyze() {
  analyzeBtn.disabled = true;
  setMessage('กำลังตรวจ IFC เบื้องต้น...');
  try {
    const result = await api('/api/analyze', { method: 'POST' });
    if (result.kind !== 'ifc') {
      setMessage(result.message || 'ตรวจไฟล์เสร็จแล้ว');
      return null;
    }
    currentAudit = result;
    renderAudit(result);
    load3dBtn.disabled = false;
    document.getElementById('stepAnalyze').classList.add('done');
    const decisions = result.revision?.decisions;
    setMessage(decisions
      ? `ตรวจ IFC เสร็จแล้ว · ใช้ผลการคัดเลือกเดิม ${decisions.carried} รายการ · ต้องตรวจใหม่ ${decisions.changed} · ตัดออก ${decisions.orphaned}`
      : 'ตรวจ IFC เสร็จแล้ว');
    return result;
  } catch (error) {
    setMessage(`ตรวจ IFC ไม่สำเร็จ: ${error.message}`);
    return null;
  } finally {
    analyzeBtn.disabled = false;
  }
}

analyzeBtn.addEventListener('click', () => runAnalyze());

let geometryLoadSeq = 0;

// Second pass after the model is on screen: proxies, furniture and other
// review-rule elements, added to the view without changing the current mode.
async function loadReviewTier(baseRequest, seq) {
  const request = { ...baseRequest, tier: 'review', append: true };
  const note = document.getElementById('previewNote');
  if (note) note.textContent = 'กำลังโหลดชิ้นส่วนรอตรวจ (เช่นเฟอร์นิเจอร์/Proxy) เพิ่มในพื้นหลัง...';
  try {
    const geometry = await api('/api/ifc/geometry', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request),
    });
    if (seq !== geometryLoadSeq) return;          // a newer load replaced the view
    if ((geometry.element_count || 0) > 0) {
      currentGeometry = mergeGeometryPayload(currentGeometry, geometry, true);
      render3dFilters(currentGeometry);
      const v = await waitForViewer();
      v.load(geometry, selectionState.overrides || {}, { append: true, keepView: true });
      renderModelTree();                     // app-tree.js
      applyViewerFilters();
      document.getElementById('viewerStatus').textContent =
        `โหลดแล้ว ${currentGeometry.element_count} ชิ้น · ${currentGeometry.triangle_count || 0} triangles · WebGL พร้อม`;
      updateSelectionSummary();
    }
    if (note) note.textContent = geometry.element_count
      ? `โหลดชิ้นส่วนรอตรวจเพิ่มแล้ว ${geometry.element_count} ชิ้น`
      : '';
  } catch (error) {
    if (note && seq === geometryLoadSeq) note.textContent = `โหลดชิ้นส่วนรอตรวจไม่สำเร็จ: ${error.message}`;
  }
}

async function runLoad3d() {
  load3dBtn.disabled = true;
  const request = geometryRequestFromControls();
  const seq = ++geometryLoadSeq;
  const subsetLabel = request.storey_ids.length
    ? `ชั้น ${geometryStoreySelect?.selectedOptions?.[0]?.textContent?.split(' · ')[0] || request.storey_ids[0]}`
    : 'ทั้งอาคาร';
  setMessage(`กำลังโหลด Geometry ${request.mode === 'full' ? 'ทั้งหมด' : 'ที่เกี่ยวกับการจำลอง'} ของ${subsetLabel}...`);

  try {
    const [geometry, selection] = await Promise.all([
      api('/api/ifc/geometry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      }),
      api('/api/selection'),
    ]);

    if (seq !== geometryLoadSeq) return false;     // a newer load/import replaced this one
    if ((geometry.element_count || 0) === 0) {
      const selectedOption = geometryStoreySelect?.selectedOptions?.[0];
      const selectedLabel = selectedOption?.textContent || subsetLabel;
      document.getElementById('viewerStatus').textContent =
        `ไม่มี Geometry 3D ใน ${selectedLabel}`;
      setMessage(
        `ไม่พบ Geometry 3D ใน ${selectedLabel} · ` +
        `เลือกชั้นที่มีวัตถุสำหรับการจำลอง หรือเปลี่ยนเป็นโหมด IFC ทั้งหมด`
      );
      return false;
    }

    currentGeometry = mergeGeometryPayload(currentGeometry, geometry, request.append);
    selectionState = selection;
    render3dFilters(currentGeometry);

    const explorerSection = document.getElementById('explorerSection');
    explorerSection.classList.remove('hidden');
    document.getElementById('viewerStatus').textContent = 'กำลังเตรียมพื้นที่แสดงผล 3D...';

    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));

    const v = await waitForViewer();
    v.load(geometry, selectionState.overrides || {}, { append: request.append });
    renderModelTree();                       // app-tree.js
    // viewer.load() always returns to the source IFC view.
    setViewerBadge('source');
    setActiveModeButton('sourceModeBtn');

    document.getElementById('viewerStatus').textContent =
      `โหลดแล้ว ${currentGeometry.element_count} ชิ้น · ${currentGeometry.triangle_count || 0} triangles · WebGL พร้อม`;
    document.getElementById('previewNote').textContent = geometry.preview_note || '';

    const loadedText = document.getElementById('loadedSubsetText');
    if (loadedText) {
      const storeyText = Object.keys(currentGeometry.storeys || {}).join(', ') || 'ไม่ระบุชั้น';
      loadedText.textContent = `ที่โหลดแล้ว: ${currentGeometry.element_count} ชิ้น · ${storeyText}`;
    }

    document.getElementById('stepExplore').classList.add('done');
    document.getElementById('stepSelect').classList.add('done');
    generateSemanticBtn.disabled = false;
    if (request.tier === 'core') loadReviewTier(request, seq);
    updateSelectionSummary();
    refreshStairOverview();
    // Partial success is said, never shown as a complete model.
    const failed = (geometry.mesh_failures || []).length;
    const partial = failed
      ? ` · ⚠ ${failed} ชิ้นสร้างรูปทรงไม่ได้ จึงไม่อยู่ในมุมมองนี้ (ตัวอย่าง: ${String(geometry.mesh_failures[0].error || '').slice(0, 80)})`
      : '';
    setMessage(
      (request.append
        ? 'เพิ่มชั้นในมุมมอง 3D แล้ว · ตรวจการคัดเลือก หรือเพิ่มชั้นถัดไป'
        : 'โหลดโมเดล 3D แล้ว · ตรวจการคัดเลือกองค์ประกอบ แล้วกด "เตรียมโมเดลคนเดิน"') + partial
    );
    return true;
  } catch (error) {
    setMessage(`โหลดโมเดล 3D ไม่สำเร็จ: ${error.message}`);
    return false;
  } finally {
    load3dBtn.disabled = false;
  }
}

load3dBtn.addEventListener('click', () => runLoad3d());

// Add one storey to the current 3D view (used by the storey filter list).
async function loadStoreyIntoView(storeyId, name) {
  if (!geometryLoadMode || !geometryStoreySelect) return false;
  const full = (geometryLoadMode.value || '').startsWith('full_');
  geometryLoadMode.value = full ? 'full_storey' : 'simulation_storey';
  geometryStoreySelect.value = String(storeyId);
  appendStoreyCheck.checked = !!currentGeometry;
  updateLargeLoadControlState();
  setMessage(`กำลังโหลดชั้น ${name} เพิ่มในมุมมอง 3D...`);
  return runLoad3d();
}

let resetArmed = null;
resetBtn.addEventListener('click', async () => {
  // Clears selections, plan edits and results: ask once more, in place.
  if (!resetArmed) {
    resetBtn.textContent = 'กดอีกครั้งเพื่อล้างโครงการ';
    resetBtn.classList.add('armed');
    resetArmed = setTimeout(() => {
      resetArmed = null;
      resetBtn.textContent = 'เริ่มโครงการใหม่';
      resetBtn.classList.remove('armed');
    }, 4000);
    return;
  }
  clearTimeout(resetArmed);
  try {
    await api('/api/project/reset', { method: 'POST' });
    window.location.reload();
  } catch (error) {
    setMessage(`เริ่มโครงการใหม่ไม่สำเร็จ: ${error.message}`);
  }
});

function renderLargeModelPanel(result) {
  const panel = document.getElementById('largeModelSection');
  if (!panel) return;
  panel.classList.remove('hidden');

  const large = result.large_model || {};
  const counts = large.simulation_counts || {};
  document.getElementById('largeModelBadge').textContent = large.detected ? 'IFC ขนาดใหญ่' : 'IFC ขนาดปกติ';
  document.getElementById('largeFileSize').textContent = `${Number(large.file_size_mb || 0).toFixed(1)} MB`;
  document.getElementById('largeWalls').textContent = counts.walls ?? 0;
  document.getElementById('largeSlabs').textContent = counts.slabs ?? 0;
  document.getElementById('largeColumns').textContent = counts.columns ?? 0;
  document.getElementById('largeBeams').textContent = counts.beams_excluded ?? 0;
  document.getElementById('largeStairs').textContent =
    (counts.stairs ?? 0) + (counts.stair_flights ?? 0);

  document.getElementById('largeModelProfile').textContent = large.structural_like
    ? 'IFC งานโครงสร้าง (ไม่มีประตู/หน้าต่าง)'
    : (large.detected ? 'IFC ขนาดใหญ่หลายระบบ' : 'IFC ขนาดปกติ');
  document.getElementById('largeModelNote').textContent = large.structural_like
    ? 'ไม่พบประตู/หน้าต่างงานสถาปัตยกรรม ต้องตรวจช่องเปิดก่อนจำลอง · คานไม่ถูกนำเข้า · แผ่นพื้นจะรวมเป็นพื้นที่เดินรายชั้น'
    : 'การโหลด 3D เลือกเฉพาะบางชั้นได้ ไม่มีผลกับโมเดลคนเดินที่สร้างจากทุกชั้น';

  const storeys = result.spatial?.storeys || [];
  geometryStoreySelect.innerHTML = '';
  let firstMeshableStoreyId = null;
  for (const storey of storeys) {
    const option = document.createElement('option');
    option.value = String(storey.entity_id);
    const z = storey.elevation_m == null ? '—' : `${Number(storey.elevation_m).toFixed(3)} m`;
    const meshCount = Number(storey.simulation_mesh_count || 0);
    option.dataset.meshCount = String(meshCount);
    option.textContent = meshCount > 0
      ? `${storey.name} · ${z} · ${meshCount} ชิ้น`
      : `${storey.name} · ${z} · ไม่มีชิ้นส่วนสำหรับจำลอง`;
    // Do not disable empty storeys completely: engineers may still inspect them
    // with Full IFC mode. But never auto-select an empty storey in simulation mode.
    if (firstMeshableStoreyId == null && meshCount > 0) {
      firstMeshableStoreyId = String(storey.entity_id);
    }
    geometryStoreySelect.appendChild(option);
  }

  geometryLoadMode.value = large.recommended_load_mode || 'simulation_all';
  if (geometryLoadMode.value === 'simulation_storey' && firstMeshableStoreyId != null) {
    geometryStoreySelect.value = firstMeshableStoreyId;
  }
  appendStoreyCheck.checked = false;
  updateLargeLoadControlState();
}

function renderAudit(result) {
  document.getElementById('auditSection').classList.remove('hidden');
  document.getElementById('categorySection').classList.remove('hidden');
  document.getElementById('projectName').textContent = result.project?.name || 'IFC Audit';
  document.getElementById('schemaBadge').textContent = result.schema || 'Unknown schema';
  document.getElementById('unitBadge').textContent =
    `${result.units?.length_symbol || '?'} → m × ${Number(result.units?.scale_to_meters ?? 1).toPrecision(4)}`;

  document.getElementById('storeyCount').textContent = result.spatial?.storeys?.length ?? 0;
  document.getElementById('productCount').textContent = result.counts?.products ?? 0;
  document.getElementById('includeCount').textContent = result.counts?.include ?? 0;
  document.getElementById('reviewCount').textContent = result.counts?.review ?? 0;
  document.getElementById('excludeCount').textContent = result.counts?.exclude ?? 0;
  document.getElementById('doorOpeningCount').textContent = result.opening_fill_breakdown?.door ?? 0;
  renderLargeModelPanel(result);

  const warningList = document.getElementById('warningList');
  warningList.innerHTML = '';
  if (!result.warnings?.length) {
    const div = document.createElement('div');
    div.className = 'warning-item ok';
    div.textContent = 'ไม่พบข้อควรระวังจากการตรวจ IFC';
    warningList.appendChild(div);
  } else {
    for (const warning of result.warnings) {
      const div = document.createElement('div');
      div.className = 'warning-item';
      div.textContent = warning;
      warningList.appendChild(div);
    }
  }

  const categoryRows = document.getElementById('categoryRows');
  categoryRows.innerHTML = '';
  for (const row of result.categories || []) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${escapeHtml(row.ifc_type)}</td>
      <td>${row.count}</td>
      <td><span class="tag ${escapeHtml(row.recommendation)}">${escapeHtml(row.recommendation)}</span></td>
      <td>${escapeHtml(row.simulation_role)}</td>
      <td>${escapeHtml(row.viswalk_mapping)}</td>
    `;
    categoryRows.appendChild(tr);
  }
}

function makeCheckRow(label, count, checked, onChange) {
  const row = document.createElement('label');
  row.className = 'check-row';
  const input = document.createElement('input');
  input.type = 'checkbox';
  input.checked = checked;
  input.addEventListener('change', () => onChange(input.checked));
  const text = document.createElement('span');
  text.textContent = label;
  const countSpan = document.createElement('span');
  countSpan.className = 'check-count';
  countSpan.textContent = count;
  row.append(input, text, countSpan);
  return row;
}

function render3dFilters(geometry) {
  activeStoreys = new Set(Object.keys(geometry.storeys || {}));
  activeCategories = new Set(Object.keys(geometry.categories || {}));

  const storeyRoot = document.getElementById('storeyFilters');
  storeyRoot.innerHTML = '';
  const loaded = geometry.storeys || {};
  // Every storey of the IFC is listed, in elevation order; storeys not yet in the
  // 3D view are unticked and load (appended) when ticked.
  const auditStoreys = currentAudit?.spatial?.storeys || [];
  const listed = new Set();
  for (const storey of auditStoreys) {
    const name = storey.name;
    if (listed.has(name)) continue;
    listed.add(name);
    if (name in loaded) {
      storeyRoot.appendChild(makeCheckRow(name, loaded[name], true, checked => {
        checked ? activeStoreys.add(name) : activeStoreys.delete(name);
        applyViewerFilters();
      }));
    } else {
      const meshCount = Number(storey.simulation_mesh_count || 0);
      const row = makeCheckRow(name, meshCount ? `ยังไม่โหลด · ${meshCount}` : 'ไม่มีชิ้นส่วน', false, async checked => {
        if (!checked) return;
        await loadStoreyIntoView(storey.entity_id, name);
      });
      row.classList.add('not-loaded');
      if (!meshCount) row.querySelector('input').disabled = true;
      storeyRoot.appendChild(row);
    }
  }
  for (const [name, count] of Object.entries(loaded)) {
    if (listed.has(name)) continue;
    storeyRoot.appendChild(makeCheckRow(name === 'Unassigned' ? 'ไม่ระบุชั้น' : name, count, true, checked => {
      checked ? activeStoreys.add(name) : activeStoreys.delete(name);
      applyViewerFilters();
    }));
  }

  const categoryRoot = document.getElementById('categoryFilters');
  categoryRoot.innerHTML = '';
  for (const [name, count] of Object.entries(geometry.categories || {}).sort((a, b) => a[0].localeCompare(b[0]))) {
    categoryRoot.appendChild(makeCheckRow(name, count, true, checked => {
      checked ? activeCategories.add(name) : activeCategories.delete(name);
      applyViewerFilters();
    }));
  }
}

const MODE_BUTTONS = ['sourceModeBtn', 'simulationModeBtn', 'overlayModeBtn', 'planModeBtn'];

function setActiveModeButton(id) {
  for (const b of MODE_BUTTONS) document.getElementById(b)?.classList.toggle('active', b === id);
  document.getElementById('planToolbar')?.classList.toggle('hidden', id !== 'planModeBtn');
}

function leavePlanIfActive() {
  const v = viewer();
  if (v?.isPlan?.()) v.exitPlan();
}

function setViewerBadge(mode) {
  // The legend explains the pedestrian-model colours (not shown over the source IFC).
  document.getElementById('viewerLegend')?.classList.toggle('hidden', !['simulation', 'overlay', 'plan'].includes(mode));
  const badge = document.getElementById('viewportIdentLabel');
  if (!badge) return;
  badge.innerHTML = {
    simulation: '3D <small>· โมเดลคนเดิน (Viswalk)</small>',
    overlay: '3D <small>· ซ้อนภาพ โมเดลคนเดินบน IFC ต้นฉบับ</small>',
    plan: 'แปลน <small>· รายระดับของโมเดลคนเดิน</small>',
  }[mode] || '3D <small>· IFC ต้นฉบับ</small>';
}

document.getElementById('overlayModeBtn').addEventListener('click', () => {
  if (!currentSemantic) {
    setMessage('ซ้อนภาพได้หลังกด "เตรียมโมเดลคนเดิน"');
    return;
  }
  leavePlanIfActive();
  viewer()?.setMode('overlay');
  setViewerBadge('overlay');
  setActiveModeButton('overlayModeBtn');
  setMessage('ซ้อนภาพ: IFC ต้นฉบับแสดงจาง ๆ ใต้โมเดลคนเดิน · ส่วนที่ไม่มีสีของโมเดลคนเดินคือสิ่งที่ไม่ได้ส่งเข้า Viswalk');
});
