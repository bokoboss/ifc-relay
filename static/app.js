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
  document.getElementById('fileMeta').textContent = selectedFile
    ? `${selectedFile.name} · ${formatBytes(selectedFile.size)}`
    : 'ยังไม่ได้เลือกไฟล์';
  if (selectedFile) openSelectedFile();
});

uploadBtn.addEventListener('click', () => openSelectedFile());

async function openSelectedFile() {
  if (!selectedFile) return;
  geometryLoadSeq += 1;          // any background load of the previous file is now stale
  uploadBtn.disabled = true;
  setMessage('กำลังนำเข้าไฟล์ต้นฉบับ...');
  try {
    const form = new FormData();
    form.append('file', selectedFile);
    form.append('carry_selection', document.getElementById('carrySelectionCheck')?.checked ? 'true' : 'false');
    const result = await api('/api/import', { method: 'POST', body: form });
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
    setMessage('นำเข้าไฟล์แล้ว · กำลังตรวจ IFC...');
    // Open the model like a BIM viewer: audit, then load the recommended
    // 3D subset (whole model, or the first storey with geometry on large IFCs).
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
    // Allow choosing the same file again (e.g. after editing it in Revit).
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
    setMessage(
      request.append
        ? 'เพิ่มชั้นในมุมมอง 3D แล้ว · ตรวจการคัดเลือก หรือเพิ่มชั้นถัดไป'
        : 'โหลดโมเดล 3D แล้ว · ตรวจการคัดเลือกองค์ประกอบ แล้วกด "เตรียมโมเดลคนเดิน"'
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

// ---- 2D plan ------------------------------------------------------------------
let planTool = 'select';

function planLevels() {
  return (currentSemantic?.levels || []).filter(l => (currentSemantic.areas || []).some(a => Number(a.level_key) === Number(l.key)));
}

document.getElementById('planModeBtn').addEventListener('click', () => {
  const v = viewer();
  const levels = planLevels();
  if (!currentSemantic || !levels.length || !v) {
    setMessage('เปิดแปลน 2D ได้หลังกด "เตรียมโมเดลคนเดิน"');
    return;
  }
  const select = document.getElementById('planLevelSelect');
  const keep = select.value;
  select.innerHTML = '';
  for (const level of levels) {
    const option = document.createElement('option');
    option.value = String(level.key);
    option.textContent = `${level.name} (${Number(level.z).toFixed(2)} ม.)`;
    select.appendChild(option);
  }
  if (keep && levels.some(l => String(l.key) === keep)) select.value = keep;
  if (v.enterPlan(Number(select.value))) {
    v.setPlanTool(planTool);
    setViewerBadge('plan');
    setActiveModeButton('planModeBtn');
    setMessage('แปลน 2D: เลื่อน/ซูมด้วยเมาส์ · เลือกเครื่องมือด้านขวาบน · การแก้ไขมีผลเมื่อกด "เตรียมโมเดลคนเดิน" อีกครั้ง');
  }
});

document.getElementById('planLevelSelect').addEventListener('change', event => {
  viewer()?.setPlanLevel(Number(event.target.value));
});

const PLAN_HINTS = {
  select: 'คลิกวัตถุเพื่อดูรายละเอียด',
  measure: 'คลิกจุดเริ่ม แล้วคลิกจุดปลาย',
  walkable: 'คลิกสองมุมของพื้นที่เดินที่ต้องการเพิ่ม',
  obstacle: 'คลิกสองมุมของสิ่งกีดขวางที่ต้องการเพิ่ม',
  passage: 'คลิกสองมุมคร่อมผนังตรงที่ต้องการเปิดทางผ่าน',
};
document.querySelectorAll('.plan-tool').forEach(button => {
  button.addEventListener('click', () => {
    planTool = button.dataset.tool;
    document.querySelectorAll('.plan-tool').forEach(b => b.classList.toggle('active', b === button));
    viewer()?.setPlanTool(planTool);
    document.getElementById('planHint').textContent = PLAN_HINTS[planTool] || '';
  });
});

window.addEventListener('plan-measure', event => {
  const { distance, final } = event.detail || {};
  document.getElementById('planHint').textContent = `ระยะ ${Number(distance).toFixed(2)} ม.${final ? '' : ' …'}`;
  if (final) setMessage(`วัดระยะบนแปลน: ${Number(distance).toFixed(3)} ม.`);
});

const EDIT_KIND_TH = { walkable: 'พื้นที่เดินเพิ่ม', obstacle: 'สิ่งกีดขวางเพิ่ม', passage: 'ทางผ่าน' };
// F-19: what the last pedestrian-model run did with each edit
const EDIT_REVIEW_TH = {
  applied: 'ใช้แล้ว',
  rebound: 'ย้ายระดับ',
  no_effect: 'ไม่มีผล',
  skipped: 'ใช้ไม่ได้',
  pending: 'รอเตรียมใหม่',
};

// ---- drawing on the plan: preview -> confirm -> save, with undo/redo ----------
let pendingShape = null;
const editHistory = { undo: [], redo: [] };

function updateUndoButtons() {
  document.getElementById('planUndoBtn').disabled = !editHistory.undo.length;
  document.getElementById('planRedoBtn').disabled = !editHistory.redo.length;
}

function segmentHitsPolygon(a, b, poly) {
  const inside = (pt) => {
    let c = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i], [xj, yj] = poly[j];
      if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) c = !c;
    }
    return c;
  };
  if (inside(a) || inside(b)) return true;
  const cross = (p, q, r) => (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]);
  for (let i = 0; i < poly.length; i += 1) {
    const c = poly[i], d = poly[(i + 1) % poly.length];
    if (cross(a, b, c) * cross(a, b, d) < 0 && cross(c, d, a) * cross(c, d, b) < 0) return true;
  }
  return false;
}

function shapeArea(poly) {
  let s = 0;
  for (let i = 0; i < poly.length; i += 1) {
    const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % poly.length];
    s += x1 * y2 - x2 * y1;
  }
  return Math.abs(s) / 2;
}

function previewSummary(shape) {
  const area = shapeArea(shape.polygon);
  const label = EDIT_KIND_TH[shape.tool] || shape.tool;
  if (shape.tool === 'passage') {
    const walls = (currentSemantic?.walls || []).filter(w => Number(w.level_key) === Number(shape.level_key)
      && segmentHitsPolygon(w.start, w.end, shape.polygon)).length;
    const polys = (currentSemantic?.obstacles || []).filter(o => Number(o.level_key) === Number(shape.level_key)
      && o.type === 'IfcWall' && o.polygon && o.polygon.some((p, i, arr) => segmentHitsPolygon(p, arr[(i + 1) % arr.length], shape.polygon))).length;
    const n = walls + polys;
    return `${label} ${area.toFixed(2)} ตร.ม. · ตัดผนัง ${n} ชิ้น` + (n ? '' : ' (ไม่โดนผนังเลย)');
  }
  return `${label} ${shape.polygon.length} มุม · ${area.toFixed(2)} ตร.ม.`;
}

async function saveEdit(shape, { record = true } = {}) {
  const result = await api('/api/edits', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind: shape.tool, level_key: shape.level_key, polygon: shape.polygon }),
  });
  renderEdits(result.edits);
  markSemanticStale();
  if (record) {
    editHistory.undo.push({ type: 'add', edit: result.edit });
    editHistory.redo = [];
  }
  updateUndoButtons();
  return result.edit;
}

async function removeEdit(edit, { record = true } = {}) {
  const result = await api(`/api/edits/${encodeURIComponent(edit.id)}`, { method: 'DELETE' });
  renderEdits(result.edits);
  markSemanticStale();
  if (record) {
    editHistory.undo.push({ type: 'delete', edit });
    editHistory.redo = [];
  }
  updateUndoButtons();
}

const asShape = edit => ({ tool: edit.kind, level_key: edit.level_key, polygon: edit.polygon });

async function undoEdit() {
  const step = editHistory.undo.pop();
  if (!step) return;
  try {
    if (step.type === 'add') {
      await removeEdit(step.edit, { record: false });
      editHistory.redo.push(step);
    } else {
      const again = await saveEdit(asShape(step.edit), { record: false });
      editHistory.redo.push({ type: 'delete', edit: again });
    }
    setMessage('ย้อนการแก้ไขแล้ว · กด "เตรียมโมเดลคนเดิน" อีกครั้งเพื่อใช้ผล');
  } catch (error) {
    setMessage(`ย้อนไม่สำเร็จ: ${error.message}`);
  }
  updateUndoButtons();
}

async function redoEdit() {
  const step = editHistory.redo.pop();
  if (!step) return;
  try {
    if (step.type === 'add') {
      const again = await saveEdit(asShape(step.edit), { record: false });
      editHistory.undo.push({ type: 'add', edit: again });
    } else {
      await removeEdit(step.edit, { record: false });
      editHistory.undo.push({ type: 'delete', edit: step.edit });
    }
    setMessage('ทำซ้ำแล้ว · กด "เตรียมโมเดลคนเดิน" อีกครั้งเพื่อใช้ผล');
  } catch (error) {
    setMessage(`ทำซ้ำไม่สำเร็จ: ${error.message}`);
  }
  updateUndoButtons();
}

function showConfirm(shape) {
  pendingShape = shape;
  document.getElementById('planConfirmText').textContent = previewSummary(shape);
  document.getElementById('planConfirm').classList.remove('hidden');
}

function hideConfirm() {
  pendingShape = null;
  document.getElementById('planConfirm').classList.add('hidden');
}

window.addEventListener('plan-shape', event => showConfirm(event.detail || {}));

document.getElementById('planConfirmBtn').addEventListener('click', async () => {
  if (!pendingShape) return;
  const shape = pendingShape;
  hideConfirm();
  try {
    const edit = await saveEdit(shape);
    setMessage(`บันทึก${EDIT_KIND_TH[shape.tool] || 'การแก้ไข'} ${edit.id} แล้ว · กด "เตรียมโมเดลคนเดิน" อีกครั้งเพื่อใช้ผล`);
  } catch (error) {
    setMessage(`บันทึกการแก้ไขไม่สำเร็จ: ${error.message}`);
  }
});
document.getElementById('planCancelBtn').addEventListener('click', hideConfirm);
document.getElementById('planUndoBtn').addEventListener('click', undoEdit);
document.getElementById('planRedoBtn').addEventListener('click', redoEdit);

document.querySelectorAll('.plan-shape').forEach(button => {
  button.addEventListener('click', () => {
    document.querySelectorAll('.plan-shape').forEach(b => b.classList.toggle('active', b === button));
    viewer()?.setPlanShape(button.dataset.shape);
  });
});

window.addEventListener('plan-draft', event => {
  const d = event.detail || {};
  const parts = [];
  if (d.shape === 'rect' && d.width != null) parts.push(`${d.width.toFixed(2)} × ${d.depth.toFixed(2)} ม.`);
  else if (d.segment != null) parts.push(`ด้านนี้ ${d.segment.toFixed(2)} ม.`);
  if (d.area != null) parts.push(`${d.area.toFixed(2)} ตร.ม.`);
  if (d.snap) parts.push({ vertex: 'จับมุม', edge: 'จับขอบ', ortho: 'แนวตั้ง/นอน' }[d.snap]);
  if (d.shape === 'poly' && d.vertices >= 3) parts.push('คลิกจุดแรกหรือ Enter เพื่อปิดรูป');
  document.getElementById('planHint').textContent = parts.join(' · ');
});

function planSizeFromInput() {
  const m = (document.getElementById('planSizeInput').value || '').trim().match(/^([\d.]+)\s*[x×*,]\s*([\d.]+)$/i);
  return m ? [Number(m[1]), Number(m[2])] : null;
}

document.getElementById('planSizeInput').addEventListener('keydown', event => {
  if (event.key !== 'Enter') return;
  const size = planSizeFromInput();
  if (!size) {
    setMessage('พิมพ์ขนาดเป็น กว้างxยาว เช่น 1.2x2');
  } else if (!viewer()?.planRectBySize(size[0], size[1])) {
    setMessage('คลิกมุมแรกบนแปลนก่อน (รูปสี่เหลี่ยม) แล้วพิมพ์ขนาด');
  }
  event.preventDefault();
});

window.addEventListener('keydown', event => {
  const v = viewer();
  if (!v?.isPlan?.()) return;
  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
  const key = event.key.toLowerCase();
  if ((event.ctrlKey || event.metaKey) && key === 'z') { event.preventDefault(); event.shiftKey ? redoEdit() : undoEdit(); return; }
  if ((event.ctrlKey || event.metaKey) && key === 'y') { event.preventDefault(); redoEdit(); return; }
  if (event.key === 'Escape') { v.planCancel(); hideConfirm(); }
  else if (event.key === 'Backspace') { event.preventDefault(); v.planUndoVertex(); }
  else if (event.key === 'Enter') {
    if (pendingShape) document.getElementById('planConfirmBtn').click();
    else v.planFinish();
  }
});

let lastEdits = [];
function renderEdits(edits) {
  const list = Array.isArray(edits) ? edits : [];
  lastEdits = list;
  viewer()?.setManualEdits(list);
  const section = document.getElementById('editsSection');
  const root = document.getElementById('editsList');
  if (!section || !root) return;
  section.classList.toggle('hidden', !list.length);
  root.innerHTML = '';
  const levelName = key => (currentSemantic?.levels || []).find(l => Number(l.key) === Number(key))?.name || `ระดับ ${key}`;
  for (const edit of list) {
    const row = document.createElement('div');
    row.className = 'edit-row';
    const xs = edit.polygon.map(p => p[0]);
    const ys = edit.polygon.map(p => p[1]);
    const w = Math.max(...xs) - Math.min(...xs);
    const h = Math.max(...ys) - Math.min(...ys);
    const review = edit.review || { state: 'pending', detail: '' };
    row.dataset.review = review.state;
    const shownLevel = review.state === 'rebound' && review.level_key != null
      ? `${levelName(edit.level_key)} → ${levelName(review.level_key)}` : levelName(edit.level_key);
    row.innerHTML = `<span class="edit-kind">${escapeHtml(edit.id)} · ${escapeHtml(EDIT_KIND_TH[edit.kind] || edit.kind)}</span>` +
      `<span>${escapeHtml(shownLevel)} · ${w.toFixed(2)} × ${h.toFixed(2)} ม.</span>` +
      `<span class="edit-review edit-review-${escapeHtml(review.state)}" title="${escapeHtml(review.detail || '')}">` +
      `${escapeHtml(EDIT_REVIEW_TH[review.state] || review.state)}</span>`;
    const del = document.createElement('button');
    del.type = 'button';
    del.textContent = 'ลบ';
    del.addEventListener('click', async () => {
      try {
        await removeEdit(edit);
        setMessage(`ลบ ${edit.id} แล้ว · กด "เตรียมโมเดลคนเดิน" อีกครั้งเพื่อใช้ผล (ย้อนได้)`);
      } catch (error) {
        setMessage(`ลบไม่สำเร็จ: ${error.message}`);
      }
    });
    row.appendChild(del);
    if (review.detail && review.state !== 'applied') {
      const why = document.createElement('div');
      why.className = 'edit-review-detail';
      why.textContent = review.detail;
      row.appendChild(why);
    }
    root.appendChild(row);
  }
  const counts = {};
  for (const edit of list) counts[edit.review?.state || 'pending'] = (counts[edit.review?.state || 'pending'] || 0) + 1;
  const summary = document.getElementById('editsReview');
  if (summary) {
    const needs = (counts.skipped || 0) + (counts.no_effect || 0) + (counts.rebound || 0) + (counts.pending || 0);
    summary.textContent = needs
      ? 'ต้องตรวจ: ' + ['skipped', 'no_effect', 'rebound', 'pending']
        .filter(k => counts[k]).map(k => `${EDIT_REVIEW_TH[k]} ${counts[k]}`).join(' · ')
      : `ใช้ครบทั้ง ${list.length} รายการ`;
    summary.classList.toggle('needs-review', needs > 0);
  }
}

async function refreshEdits() {
  try {
    renderEdits((await api('/api/edits')).edits);
  } catch (error) {
    // optional panel
  }
}

document.getElementById('sourceModeBtn').addEventListener('click', () => {
  leavePlanIfActive();
  viewer()?.setMode('source');
  setViewerBadge('source');
  setActiveModeButton('sourceModeBtn');
  document.getElementById('stepPreview').classList.remove('done');
});

document.getElementById('simulationModeBtn').addEventListener('click', () => {
  leavePlanIfActive();
  viewer()?.setMode('simulation');
  setViewerBadge('simulation');
  setActiveModeButton('simulationModeBtn');
  document.getElementById('stepPreview').classList.add('done');
  setMessage('โมเดลคนเดิน: แสดงพื้นที่เดิน สิ่งกีดขวาง และบันไดที่จะส่งเข้า Viswalk · ประตูเป็นช่องเปิด หน้าต่างไม่ใช่ทางเดิน');
});

document.getElementById('fitModelBtn').addEventListener('click', () => viewer()?.fitModel());
document.getElementById('fitSelectionBtn').addEventListener('click', () => viewer()?.fitSelection());
document.getElementById('isolateBtn').addEventListener('click', () => {
  if (!viewer()?.isolateSelected()) setMessage('เลือกวัตถุใน 3D ก่อนใช้ "แยกแสดง"');
});
document.getElementById('showAllBtn').addEventListener('click', () => viewer()?.showAll());
document.getElementById('wireframeBtn').addEventListener('click', event => {
  const enabled = viewer()?.toggleWireframe();
  event.currentTarget.textContent = enabled ? 'ผิวทึบ' : 'โครงลวด';
});

window.addEventListener('ifc-element-selected', event => {
  selectedElement = event.detail;
  document.getElementById('semanticSourceBox')?.classList.add('hidden');
  renderInspector(selectedElement);
});

const SEMANTIC_KIND_TH = {
  area: 'พื้นที่เดิน (Area)',
  wall: 'ผนัง (Obstacle)',
  column: 'เสา (Obstacle)',
  obstacle: 'สิ่งกีดขวาง (Obstacle)',
  vertical_connection: 'บันได / ทางลาด (Ramp)',
  stair_direction: 'บันได / ทางลาด (Ramp)',
  isolated_zone: 'พื้นที่ที่เดินไปไม่ถึง (ตรวจการเชื่อมต่อ)',
};

// A pedestrian-model object was clicked: show what Viswalk gets and where it came
// from. Status buttons act on the source IFC element when there is exactly one.
window.addEventListener('semantic-element-selected', event => {
  const { kind, source, sourceGuids, sourceItems } = event.detail || {};
  const src = source || {};
  const single = sourceItems?.length === 1 && sourceGuids?.length === 1 ? sourceItems[0] : null;
  selectedElement = single;
  document.getElementById('emptyInspector').classList.add('hidden');
  document.getElementById('inspectorContent').classList.remove('hidden');
  document.getElementById('selectedName').textContent = src.name || SEMANTIC_KIND_TH[kind] || kind;
  document.getElementById('selectedType').textContent =
    `${SEMANTIC_KIND_TH[kind] || kind}${single ? ` ← ${single.ifc_type}` : ''}`;
  const level = (currentSemantic?.levels || []).find(l => Number(l.key) === Number(src.level_key ?? src.start_level));
  document.getElementById('selectedStorey').textContent = kind === 'vertical_connection' || kind === 'stair_direction'
    ? `ระดับ ${src.start_level} → ${src.end_level}`
    : (level?.name || `ระดับ ${src.level_key ?? '—'}`);
  document.getElementById('selectedGuid').textContent = sourceGuids?.length ? sourceGuids[0] : '— (สร้างโดยระบบ)';
  document.getElementById('selectedAuto').textContent = single ? (single.recommendation || 'review') : '—';
  document.getElementById('selectedMapping').textContent = `Key ${src.key ?? '—'}${src.type ? ` · ${src.type}` : ''}`;
  document.getElementById('selectedRole').textContent = src.height != null
    ? `สูง ${Number(src.height).toFixed(2)} ม.${src.replicated_from_level ? ` · คัดลอกจากระดับ ${src.replicated_from_level}` : ''}`
    : (src.rise != null ? `สูงขึ้น ${Number(src.rise).toFixed(2)} ม. · ${src.steps ?? '?'} ขั้น` : '—');
  const override = single ? (selectionState.overrides?.[single.global_id] || 'auto') : null;
  document.getElementById('effectiveStatus').textContent = single
    ? `กำหนดเอง: ${STATUS_TH[override] || override} · ผลที่ใช้: ${STATUS_TH[effectiveStatus(single)] || effectiveStatus(single)}`
    : (sourceGuids?.length > 1 ? `รวมจาก ${sourceGuids.length} ชิ้น · เปลี่ยนสถานะได้ที่ชิ้นต้นฉบับ` : 'สร้างโดยระบบ ไม่มีชิ้นต้นฉบับ');
  document.querySelectorAll('.status-btn').forEach(button => {
    button.disabled = !single;
    button.classList.toggle('active', !!single && button.dataset.status === override);
  });
  document.getElementById('semanticNote').textContent = kind === 'isolated_zone'
    ? `พื้นที่ ${Number(src.area_m2).toFixed(1)} ตร.ม. ที่คนเดินจากเครือข่ายหลักไปไม่ถึง · ตรวจประตู/ช่องเปิดหรือบันไดที่ขาด`
    : (src.generated
      ? 'สร้างโดยระบบ (เช่นช่องว่างในพื้น) · ไม่มีชิ้นใน IFC'
      : 'วัตถุในโมเดลคนเดิน · กดชื่อด้านล่างเพื่อไปที่ชิ้นต้นฉบับใน IFC');

  const box = document.getElementById('semanticSourceBox');
  const list = document.getElementById('semanticSourceList');
  list.innerHTML = '';
  box.classList.toggle('hidden', !sourceGuids?.length);
  for (const guid of (sourceGuids || []).slice(0, 30)) {
    const item = (sourceItems || []).find(i => i.global_id === guid);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'source-link';
    button.textContent = item ? `${item.ifc_type} · ${item.name || guid}` : `${guid} (ยังไม่โหลดใน 3D)`;
    button.disabled = !item;
    button.addEventListener('click', () => {
      if (viewer()?.showSource(guid)) {
        setViewerBadge('source');
        setActiveModeButton('sourceModeBtn');
      }
    });
    list.appendChild(button);
  }
});

const STATUS_TH = { auto: 'อัตโนมัติ', include: 'นำเข้า', review: 'รอตรวจ', exclude: 'ไม่ใช้' };

function renderInspector(item) {
  if (!item) return;
  document.querySelectorAll('.status-btn').forEach(button => { button.disabled = false; });
  document.getElementById('emptyInspector').classList.add('hidden');
  document.getElementById('inspectorContent').classList.remove('hidden');
  document.getElementById('selectedName').textContent = item.name || item.ifc_type;
  document.getElementById('selectedType').textContent = item.ifc_type || '—';
  document.getElementById('selectedStorey').textContent = item.storey_name || 'ไม่ระบุชั้น';
  document.getElementById('selectedGuid').textContent = item.global_id || '—';
  document.getElementById('selectedAuto').textContent = item.recommendation || 'review';
  document.getElementById('selectedMapping').textContent = item.viswalk_mapping || '—';
  document.getElementById('selectedRole').textContent = item.simulation_role || '—';

  const override = selectionState.overrides?.[item.global_id] || 'auto';
  const effective = effectiveStatus(item);
  document.getElementById('effectiveStatus').textContent =
    `กำหนดเอง: ${STATUS_TH[override] || override} · ผลที่ใช้: ${STATUS_TH[effective] || effective}`;

  document.querySelectorAll('.status-btn').forEach(button => {
    button.classList.toggle('active', button.dataset.status === override);
  });

  const note = document.getElementById('semanticNote');
  if (item.simulation_role === 'opening') {
    note.textContent = 'ประตู: แปลงเป็นช่องเปิดให้คนเดินผ่าน ไม่ใช่สิ่งกีดขวาง';
  } else if (item.simulation_role === 'wall_closure') {
    note.textContent = 'หน้าต่าง: ไม่ส่งเป็นวัตถุใน Vissim และไม่ถือเป็นทางเดิน แสดงไว้เพื่อให้เห็นแนวผนังเท่านั้น';
  } else {
    note.textContent = `การแปลงสำหรับการจำลอง: ${item.viswalk_mapping || 'ต้องตรวจสอบ'}`;
  }
}

document.querySelectorAll('.status-btn').forEach(button => {
  button.addEventListener('click', async () => {
    if (!selectedElement?.global_id) return;
    const status = button.dataset.status;
    try {
      const result = await api('/api/selection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ global_id: selectedElement.global_id, status }),
      });
      selectionState = result.selection;
      viewer()?.setOverrides(selectionState.overrides || {});
      renderInspector(selectedElement);
      updateSelectionSummary();
      if (currentSemantic) {
        setExportReady(false);
        currentValidation = null;
        currentBuild = null;
        document.getElementById('stepSemantic').classList.remove('done');
        const enginePath = document.getElementById('semanticEnginePath');
        enginePath.classList.remove('hidden');
        enginePath.textContent = 'การคัดเลือกเปลี่ยนแล้ว · โมเดลคนเดินเดิมใช้ไม่ได้ กด "เตรียมโมเดลคนเดิน" อีกครั้ง';
      }
      setMessage(`${selectedElement.ifc_type} ${selectedElement.global_id}: ${status}`);
    } catch (error) {
      setMessage(`บันทึกการคัดเลือกไม่สำเร็จ: ${error.message}`);
    }
  });
});


function renderSemanticSummary(result) {
  const summary = result.summary || result.ifc_semantic?.summary || {};
  const warnings = result.warnings || result.ifc_semantic?.warnings || [];
  document.getElementById('semanticSection').classList.remove('hidden');
  document.getElementById('semanticLevels').textContent = summary.levels ?? 0;
  document.getElementById('semanticSourceSlabs').textContent = summary.walkable_source_slabs ?? 0;
  document.getElementById('semanticAreas').textContent = summary.walkable_regions ?? summary.walkable_areas ?? 0;
  document.getElementById('semanticVoidMasks').textContent = summary.walkable_void_masks ?? 0;
  document.getElementById('semanticLogicalWalls').textContent = summary.logical_walls ?? 0;
  document.getElementById('semanticWallSegments').textContent = summary.physical_wall_segments ?? 0;
  document.getElementById('semanticDoorOpenings').textContent = summary.door_openings_applied ?? 0;
  document.getElementById('semanticObstacles').textContent =
    (summary.columns ?? 0) + (summary.obstacles ?? 0);
  document.getElementById('semanticVertical').textContent = summary.vertical_connections ?? 0;
  document.getElementById('semanticWarnings').textContent = summary.warnings ?? warnings.length;
  document.getElementById('doorLogicText').textContent =
    `ประตูที่เลือก ${summary.included_doors ?? 0} บาน → ตัดช่องในผนังได้ ${summary.door_openings_applied ?? 0} ช่อง · ` +
    `ช่องเปิดไม่มีประตู เปิดใช้ ${summary.unfilled_openings_applied ?? 0} จาก ${summary.unfilled_openings ?? 0} ช่อง · ` +
    `ใช้หน้าต่างเป็นช่องเปิด ${summary.windows_used_as_openings ?? 0}`;

  renderOpeningCandidates(
    result.model?.ifc_semantic?.opening_candidates || result.ifc_semantic?.opening_candidates || [],
  );
  renderVerticalConnections(result.model?.vertical_connections || result.vertical_connections || []);
  renderOffLevelSlabs(result.model?.ifc_semantic?.off_level_slabs || result.ifc_semantic?.off_level_slabs || []);
  renderConnectivity(result.model?.ifc_semantic?.connectivity || result.ifc_semantic?.connectivity || null);
  refreshEdits();

  const root = document.getElementById('semanticWarningList');
  root.innerHTML = '';
  if (!warnings.length) {
    const item = document.createElement('div');
    item.className = 'warning-item ok';
    item.textContent = 'เตรียมโมเดลคนเดินโดยไม่มีข้อควรระวัง';
    root.appendChild(item);
  } else {
    // Raw converter notes (English, technical). What needs action is already in
    // the "ตรวจใน Viswalk" tab, so these stay folded.
    const box = document.createElement('details');
    box.className = 'tech-notes';
    const head = document.createElement('summary');
    head.textContent = `บันทึกทางเทคนิคจากการแปลง (${warnings.length})`;
    box.appendChild(head);
    for (const warning of warnings) {
      const item = document.createElement('div');
      item.className = 'warning-item';
      item.textContent = warning;
      box.appendChild(item);
    }
    root.appendChild(box);
  }
}

const DIRECTION_REASON_TH = {
  'footprint is not a straight flight': 'แนวบันไดไม่ตรง',
  'both ends of the flight reach similar heights': 'ปลายทั้งสองข้างสูงใกล้กัน หาทิศขึ้นไม่ได้',
};

function renderVerticalConnections(connections) {
  const section = document.getElementById('verticalSection');
  const root = document.getElementById('verticalList');
  if (!section || !root) return;
  root.innerHTML = '';
  section.classList.toggle('hidden', !connections.length);
  for (const c of connections) {
    const row = document.createElement('div');
    row.className = 'vertical-row';
    const badge = document.createElement('span');
    const review = c.direction_status !== 'derived_from_geometry';
    badge.className = `dir-badge ${review ? 'dir-review' : 'dir-ok'}`;
    badge.textContent = review ? 'ต้องตรวจทิศ' : 'ทิศจาก Geometry';
    const text = document.createElement('span');
    const kind = c.type === 'ramp' ? 'ทางลาด' : 'บันได';
    const offsets = (Number(c.start_z_offset || 0) || Number(c.end_z_offset || 0))
      ? ` · offset ${Number(c.start_z_offset || 0).toFixed(2)}/${Number(c.end_z_offset || 0).toFixed(2)} m` : '';
    text.textContent = `#${c.key} ${kind} ระดับ ${c.start_level} → ${c.end_level} · สูง ${Number(c.rise || 0).toFixed(2)} m` +
      (c.steps ? ` · ${c.steps} ขั้น` : '') + offsets + (review && c.direction_reason ? ` · ${DIRECTION_REASON_TH[c.direction_reason] || c.direction_reason}` : '');
    row.append(badge, text);
    root.appendChild(row);
  }
}

let stairOverview = null;

function renderStairOverview(overview) {
  stairOverview = overview;
  const counts = overview?.counts || { units: 0, include: 0, review: 0, exclude: 0 };
  document.getElementById('stairUnits').textContent = counts.units;
  document.getElementById('stairIncluded').textContent = counts.include;
  document.getElementById('stairReview').textContent = counts.review;
  const btn = document.getElementById('stairBulkBtn');
  if (btn) btn.disabled = !counts.review;
  document.getElementById('stairResetBtn')?.classList.toggle('hidden', !counts.include);
}

async function refreshStairOverview() {
  try {
    renderStairOverview(await api('/api/stairs'));
  } catch (error) {
    renderStairOverview(null);
  }
}

function hideStairConfirm() {
  document.getElementById('stairConfirm')?.classList.add('hidden');
}

async function applyStairBulk(status) {
  const result = await api('/api/stairs/bulk', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
  selectionState = result.selection;
  viewer()?.setOverrides(selectionState.overrides || {});
  updateSelectionSummary();
  renderStairOverview(result.overview);
  if (currentSemantic) {
    const enginePath = document.getElementById('semanticEnginePath');
    enginePath?.classList.remove('hidden');
    if (enginePath) enginePath.textContent = 'การคัดเลือกเปลี่ยนแล้ว · โมเดลคนเดินเดิมใช้ไม่ได้ กด "เตรียมโมเดลคนเดิน" อีกครั้ง';
  }
  return result;
}

document.getElementById('stairBulkBtn')?.addEventListener('click', async () => {
  await refreshStairOverview();
  const c = stairOverview?.counts;
  if (!c || !c.review) {
    setMessage('ไม่มีบันไดหรือทางลาดที่รอตรวจสอบ');
    return;
  }
  document.getElementById('stairConfirmText').textContent =
    `พบบันได/ทางลาด ${c.units} ชุด (${c.flights} flight) · นำเข้าแล้ว ${c.include} · รอตรวจสอบ ${c.review} · ไม่ใช้ ${c.exclude}. ` +
    `จะตั้ง ${c.review} ชุดที่รอตรวจสอบให้เป็น "นำเข้า" (ชุดที่ตั้งเป็น "ไม่ใช้" จะไม่ถูกเปลี่ยน และไม่สร้างบันไดซ้ำจาก flight ลูก)`;
  document.getElementById('stairConfirm').classList.remove('hidden');
});

document.getElementById('stairCancelBtn')?.addEventListener('click', hideStairConfirm);

document.getElementById('stairConfirmBtn')?.addEventListener('click', async () => {
  hideStairConfirm();
  try {
    const result = await applyStairBulk('include');
    setMessage(`นำเข้าบันได/ทางลาดแล้ว ${result.overview.counts.include} ชุด · กด "เตรียมโมเดลคนเดิน" เพื่อดูลูกศรทิศขึ้นใน 3D`);
  } catch (error) {
    setMessage(`นำเข้าบันไดไม่สำเร็จ: ${error.message}`);
  }
});

document.getElementById('stairResetBtn')?.addEventListener('click', async () => {
  try {
    await applyStairBulk('auto');
    setMessage('คืนบันได/ทางลาดทั้งหมดเป็น "รอตรวจสอบ" แล้ว');
  } catch (error) {
    setMessage(`คืนสถานะบันไดไม่สำเร็จ: ${error.message}`);
  }
});

function renderConnectivity(con) {
  const note = document.getElementById('connectivityNote');
  if (!note) return;
  if (!con || con.error || !('zones' in con)) {
    note.className = 'connectivity-note warn';
    note.textContent = `ตรวจการเชื่อมต่อไม่สำเร็จ${con?.error ? ` (${con.error})` : ''} · ยังไม่รู้ว่าพื้นที่เดินต่อถึงกันหรือไม่ · ยังสร้างไฟล์ได้ แต่ต้องตรวจทางเชื่อมใน Viswalk`;
    return;
  }
  const iso = con.isolated_zones || [];
  const loose = con.stairs_not_linked || [];
  const ok = !iso.length && !loose.length;
  note.className = `connectivity-note ${ok ? 'ok' : 'warn'}`;
  note.textContent = ok
    ? `ตรวจการเชื่อมต่อทางเรขาคณิต: พื้นที่เดินต่อถึงกันหมด · บันไดเชื่อม ${con.stairs_linked} ตัว (ยังไม่ใช่การตรวจเส้นทางเดินใน Viswalk)`
    : `ตรวจการเชื่อมต่อทางเรขาคณิต: พื้นที่ที่เดินไปไม่ถึง ${iso.length} แห่ง (${Number(con.isolated_area_m2).toFixed(1)} ตร.ม., แสดงเป็นสีแดงใน 3D)` +
      (loose.length ? ` · บันไดที่ปลายไม่ถึงพื้นที่เดิน ${loose.length} ตัว` : '') +
      ` · บันไดเชื่อมแล้ว ${con.stairs_linked} ตัว`;
}

function renderOffLevelSlabs(slabs) {
  const section = document.getElementById('offLevelSection');
  const root = document.getElementById('offLevelList');
  if (!section || !root) return;
  root.innerHTML = '';
  section.classList.toggle('hidden', !slabs.length);
  for (const slab of slabs) {
    const row = document.createElement('label');
    row.className = 'check-row opening-row';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = slab.decision === 'include';
    input.disabled = !slab.global_id;
    const text = document.createElement('span');
    text.textContent = `${slab.name} · ชั้น ${slab.level_key} · ${Number(slab.offset_m) > 0 ? '+' : ''}${Number(slab.offset_m).toFixed(2)} ม. จากพื้นชั้น · ${Number(slab.area_m2).toFixed(1)} ตร.ม.`;
    const tag = document.createElement('span');
    tag.className = `tag ${slab.decision === 'include' ? 'include' : 'review'}`;
    tag.textContent = slab.decision === 'include' ? 'ใช้เป็นพื้นเดิน' : 'รอตรวจ';
    input.addEventListener('change', async () => {
      input.disabled = true;
      try {
        await api('/api/selection', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ global_id: slab.global_id, status: input.checked ? 'include' : 'auto' }),
        });
        slab.decision = input.checked ? 'include' : 'auto';
        markSemanticStale();
        setMessage('บันทึกการใช้แผ่นพื้นแล้ว · กด "เตรียมโมเดลคนเดิน" อีกครั้งก่อนตรวจหรือสร้างไฟล์');
      } catch (error) {
        input.checked = !input.checked;
        setMessage(`บันทึกไม่สำเร็จ: ${error.message}`);
      } finally {
        input.disabled = !slab.global_id;
      }
    });
    row.append(input, text, tag);
    root.appendChild(row);
  }
}

function renderOpeningCandidates(candidates) {
  const section = document.getElementById('openingCandidateSection');
  const root = document.getElementById('openingCandidateList');
  if (!section || !root) return;
  root.innerHTML = '';
  section.classList.toggle('hidden', !candidates.length);
  const ordered = [...candidates].sort((a, b) =>
    (a.classification === 'passage_candidate' ? 0 : 1) - (b.classification === 'passage_candidate' ? 0 : 1));
  const SHOWN = 500;            // the list is complete; only the display is capped
  if (ordered.length > SHOWN) {
    const more = document.createElement('p');
    more.className = 'opening-candidates-note';
    more.textContent = `แสดง ${SHOWN} จาก ${ordered.length} ช่อง (ที่อาจเป็นทางเดินอยู่ก่อน) · checklist ใช้ครบทุกช่อง`;
    root.appendChild(more);
  }
  for (const c of ordered.slice(0, SHOWN)) {
    const row = document.createElement('label');
    row.className = 'check-row opening-row';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = c.decision === 'include';
    input.disabled = !c.global_id;
    const text = document.createElement('span');
    const where = c.host_wall_name || c.host_wall_global_id || 'ผนัง';
    text.textContent = `${where} · กว้าง ${Number(c.width).toFixed(2)} × สูง ${Number(c.height).toFixed(2)} ม. · ขอบล่าง ${Number(c.sill).toFixed(2)} ม.` +
      (c.level_key != null ? ` · ชั้น ${c.level_key}` : '');
    const tag = document.createElement('span');
    tag.className = `tag ${c.classification === 'passage_candidate' ? 'review' : 'exclude'}`;
    tag.textContent = c.classification === 'passage_candidate' ? 'อาจเป็นทางเดิน' : 'ไม่น่าเป็นทางเดิน';
    input.addEventListener('change', async () => {
      input.disabled = true;
      try {
        await api('/api/selection', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ global_id: c.global_id, status: input.checked ? 'include' : 'auto' }),
        });
        c.decision = input.checked ? 'include' : 'auto';
        markSemanticStale();
        setMessage('บันทึกการเปิดช่องแล้ว · กด "เตรียมโมเดลคนเดิน" อีกครั้งก่อนตรวจหรือสร้างไฟล์');
      } catch (error) {
        input.checked = !input.checked;
        setMessage(`บันทึกการเปิดช่องไม่สำเร็จ: ${error.message}`);
      } finally {
        input.disabled = false;
      }
    });
    row.append(input, text, tag);
    root.appendChild(row);
  }
}

generateSemanticBtn.addEventListener('click', async () => {
  generateSemanticBtn.disabled = true;
  generateSemanticBtn.setAttribute('aria-busy', 'true');
  setMessage('กำลังเตรียมโมเดลคนเดิน: รวมพื้นที่เดิน แปลงผนังและช่องเปิดตามองค์ประกอบที่เลือก...');
  try {
    const result = await api('/api/ifc/semantic', { method: 'POST' });
    currentSemantic = result.model;
    currentValidation = null;
    currentBuild = null;
    renderSemanticSummary(result);
    dock.select('details', { open: false });   // counts update; the viewer keeps its size
    setExportReady(true);
    setBuildOutputReady(false);
    document.getElementById('stepSemantic').classList.add('done');

    // The source IFC viewer is already open. After generating semantic geometry,
    // switch it to the simulation-facing walkable/obstacle model automatically.
    // Preview failures must not discard an otherwise successful model export.
    let previewMeshes = 0;
    let previewIssue = '';
    try {
      const v = await waitForViewer();
      if (typeof v.loadSemantic === 'function') {
        previewMeshes = Number(v.loadSemantic(result.model) || 0);
      }
      if (previewMeshes > 0 && v.isPlan?.()) {
        // Regenerated while drawing on the plan: stay on the same level.
        v.setPlanLevel(Number(document.getElementById('planLevelSelect').value));
        document.getElementById('stepPreview').classList.add('done');
      } else if (previewMeshes > 0) {
        v.setMode('simulation');
        setViewerBadge('simulation');
        setActiveModeButton('simulationModeBtn');
        document.getElementById('stepPreview').classList.add('done');
      } else {
        previewIssue = 'ไม่พบ Geometry ที่สามารถแสดงใน 3D Preview ได้';
      }
    } catch (error) {
      previewIssue = error?.message || String(error);
    }

    const enginePath = document.getElementById('semanticEnginePath');
    enginePath.classList.remove('hidden');
    enginePath.textContent = 'เตรียมข้อมูลโมเดลคนเดินแล้ว · สามารถดาวน์โหลด Semantic/Engine JSON หรือดำเนินการตรวจสอบ Geometry';
    if (previewMeshes > 0) {
      const summary = result.summary || result.ifc_semantic?.summary || {};
      document.getElementById('viewerStatus').textContent =
        `โมเดลคนเดิน · พื้นที่เดิน ${summary.walkable_regions ?? summary.walkable_areas ?? 0} · ผนัง ${summary.physical_wall_segments ?? 0} · Preview ${previewMeshes} ชิ้น`;
      setMessage('เตรียมโมเดลคนเดินเสร็จแล้ว · กำลังแสดงพื้นที่เดินและสิ่งกีดขวางใน 3D · โปรดตรวจสอบก่อนสร้างไฟล์ Viswalk');
    } else {
      setMessage(`เตรียมข้อมูลโมเดลคนเดินแล้ว แต่เปิด Preview ไม่สำเร็จ: ${previewIssue} · ยังสามารถดาวน์โหลด JSON และตรวจสอบปัญหาได้`);
    }
  } catch (error) {
    setMessage(`เตรียมโมเดลคนเดินไม่สำเร็จ: ${error.message}`);
  } finally {
    generateSemanticBtn.disabled = false;
    generateSemanticBtn.removeAttribute('aria-busy');
  }
});

downloadSemanticTopBtn.addEventListener('click', () => {
  if (!currentSemantic) return;
  startDownload('/api/ifc/semantic/download');
  setMessage('กำลังดาวน์โหลด Semantic JSON...');
});

downloadEngineTopBtn.addEventListener('click', () => {
  if (!currentSemantic) return;
  startDownload('/api/ifc/semantic/engine-download');
  setMessage('กำลังดาวน์โหลด geometry_ifc_v03.json สำหรับ Engine...');
});

exportEngineBtn.addEventListener('click', async () => {
  exportEngineBtn.disabled = true;
  try {
    const result = await api('/api/ifc/semantic/export-engine-input', { method: 'POST' });
    const enginePath = document.getElementById('semanticEnginePath');
    enginePath.classList.remove('hidden');
    enginePath.textContent = `บันทึกแล้ว: ${result.path}`;
    setMessage('ส่งออกไฟล์สำหรับ Engine แล้ว');
  } catch (error) {
    setMessage(`ส่งออกไฟล์สำหรับ Engine ไม่สำเร็จ: ${error.message}`);
  } finally {
    exportEngineBtn.disabled = false;
  }
});


let currentGate = null;
let validationBusy = false;
let buildBusy = false;

async function refreshGate() {
  try {
    currentGate = await api('/api/gate');
  } catch (error) {
    currentGate = null;
  }
  renderGate(currentGate);
  return currentGate;
}

// ---------------------------------------------------------------------------
// Review queue (UX-03): every check item opens to the objects or places it is
// about, and "ดูตำแหน่ง" takes the viewer there. Items without a location say so.
// ---------------------------------------------------------------------------
const GUID_RX = /^[0-9A-Za-z_$]{22}$/;
const ZONE_RX = /^L(-?\d+)@(-?[\d.]+),(-?[\d.]+)~([\d.]+)$/;
const END_TH = { start: 'ปลายล่าง', end: 'ปลายบน', bottom: 'ปลายล่าง', top: 'ปลายบน' };
const ITEMS_SHOWN = 60;
const ENGINE_ISSUE_TH = {
  obstacle_outside_walkable: 'สิ่งกีดขวางอยู่นอกพื้นที่เดิน',
  obstacle_overlap: 'สิ่งกีดขวางซ้อนกัน',
  level_without_walkable_area: 'ระดับที่ไม่มีพื้นที่เดิน',
  vertical_connection_not_on_start_area: 'ปลายล่างบันได/ทางลาดไม่แตะพื้นที่เดิน',
  vertical_connection_not_on_end_area: 'ปลายบนบันได/ทางลาดไม่แตะพื้นที่เดิน',
};

function levelNameOf(key) {
  return (currentSemantic?.levels || []).find(l => Number(l.key) === Number(key))?.name || `ระดับ ${key}`;
}

function describeIdentity(id) {
  const zone = String(id).match(ZONE_RX);
  if (zone) {
    const [, level, x, y, area] = zone;
    return { kind: 'zone', level: Number(level), x: Number(x), y: Number(y),
      radius: Math.min(Math.max(Math.sqrt(Number(area) / Math.PI), 1), 10),
      label: `${levelNameOf(level)} · ${Number(area).toFixed(1)} ตร.ม. ที่ (${Number(x).toFixed(1)}, ${Number(y).toFixed(1)})` };
  }
  if (/^E\d+$/.test(id)) {
    const edit = lastEdits.find(e => e.id === id);
    if (!edit) return { kind: 'none', label: `${id} (ลบไปแล้ว)` };
    const xs = edit.polygon.map(p => p[0]), ys = edit.polygon.map(p => p[1]);
    return { kind: 'zone', level: Number(edit.level_key),
      x: (Math.min(...xs) + Math.max(...xs)) / 2, y: (Math.min(...ys) + Math.max(...ys)) / 2,
      radius: Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), 1) / 2 + 0.5,
      label: `${id} · ${EDIT_KIND_TH[edit.kind] || edit.kind} · ${levelNameOf(edit.level_key)}` };
  }
  const [head, rest] = String(id).split(/[:@]/);
  if (GUID_RX.test(head)) {
    const suffix = rest ? (END_TH[rest] || (rest.startsWith('L') ? levelNameOf(rest.slice(1)) : rest)) : '';
    return { kind: 'source', guid: head, label: head + (suffix ? ` · ${suffix}` : '') };
  }
  return { kind: 'none', label: String(id) };
}

function focusIdentity(target) {
  const v = viewer();
  if (!v) return;
  if (target.kind === 'source') {
    if (!v.hasSource(target.guid)) {
      setMessage(`ยังไม่ได้โหลด ${target.guid} ใน 3D · เปิดชั้นหรือประเภทขององค์ประกอบนี้ในแผงซ้ายแล้วลองอีกครั้ง หรือค้นด้วย GlobalId ใน Viswalk`);
      return;
    }
    document.getElementById('sourceModeBtn').click();
    v.showSource(target.guid);
    setMessage(`แสดง ${target.guid} ในโมเดลต้นฉบับ`);
    return;
  }
  if (target.kind === 'zone') {
    if (!v.isPlan()) document.getElementById('planModeBtn').click();
    const select = document.getElementById('planLevelSelect');
    if (![...select.options].some(o => Number(o.value) === target.level)) {
      setMessage(`${levelNameOf(target.level)} ไม่มีพื้นที่เดินให้แสดงในแปลน`);
      return;
    }
    if (Number(select.value) !== target.level) {
      select.value = String(target.level);
      select.dispatchEvent(new Event('change'));
    }
    requestAnimationFrame(() => requestAnimationFrame(() => v.focusPlanPoint(target.x, target.y, target.radius)));
    setMessage(`แปลน ${levelNameOf(target.level)}: วงสีส้มคือตำแหน่งที่ต้องตรวจ`);
  }
}

function renderGate(gate) {
  const section = document.getElementById('gateSection');
  const root = document.getElementById('gateList');
  if (!section || !root) return;
  section.classList.toggle('hidden', !gate);
  const open = new Set([...root.querySelectorAll('details[open]')].map(d => d.dataset.item));
  root.innerHTML = '';
  if (!gate) return;
  const order = { block: 0, check: 1, info: 2 };
  for (const item of [...gate.items].sort((a, b) => order[a.policy] - order[b.policy])) {
    const row = document.createElement('details');
    row.className = `gate-row ${item.policy}`;
    row.dataset.item = item.id;
    row.open = open.has(item.id);
    const head = document.createElement('summary');
    head.className = 'gate-head';
    const chip = document.createElement('span');
    chip.className = `gate-chip ${item.policy}`;
    chip.textContent = { block: 'ต้องแก้', check: 'ตรวจใน Viswalk', info: 'ข้อมูล' }[item.policy];
    const title = document.createElement('strong');
    title.textContent = item.title;
    const count = document.createElement('span');
    count.className = 'gate-count';
    count.textContent = item.count;
    head.append(chip, title, count);
    const detail = document.createElement('small');
    detail.className = 'gate-detail';
    detail.textContent = item.detail;
    row.append(head, detail);
    // The object list is built on first open: big models have thousands.
    row.addEventListener('toggle', () => {
      if (!row.open || row.querySelector('.gate-items')) return;
      const list = document.createElement('ul');
      list.className = 'gate-items';
      const ids = item.identities || [];
      for (const id of ids.slice(0, ITEMS_SHOWN)) {
        const target = describeIdentity(id);
        const li = document.createElement('li');
        const label = document.createElement('span');
        label.className = target.kind === 'source' ? 'gate-item-label mono' : 'gate-item-label';
        label.textContent = target.label;
        li.appendChild(label);
        if (target.kind !== 'none') {
          const go = document.createElement('button');
          go.type = 'button';
          go.className = 'gate-locate';
          go.textContent = target.kind === 'source' ? 'ดูในโมเดล' : 'ดูตำแหน่ง';
          go.addEventListener('click', () => {
            root.querySelectorAll('.gate-items li.current').forEach(n => n.classList.remove('current'));
            li.classList.add('current');
            focusIdentity(target);
          });
          li.appendChild(go);
        }
        list.appendChild(li);
      }
      const more = item.count - Math.min(ids.length, ITEMS_SHOWN);
      if (more > 0) {
        const li = document.createElement('li');
        li.className = 'gate-items-more';
        li.textContent = `และอีก ${more} รายการ · ครบทุกรายการใน checklist ที่ได้ตอนสร้างไฟล์`;
        list.appendChild(li);
      }
      if (!ids.length) {
        const li = document.createElement('li');
        li.className = 'gate-items-more';
        li.textContent = 'รายการนี้ไม่มีตำแหน่งในโมเดลให้ชี้';
        list.appendChild(li);
      }
      row.appendChild(list);
    });
    root.appendChild(row);
  }
  const summary = document.getElementById('gateSummary');
  summary.className = `gate-summary ${gate.passed ? 'ok' : 'warn'}`;
  summary.textContent = !gate.passed
    ? `สร้างไฟล์ไม่ได้ · Geometry Engine สร้างไฟล์จากโมเดลนี้ไม่ได้ (${gate.blocked.length} รายการ)`
    : gate.to_check.length
      ? `สร้างไฟล์ได้ · มี ${gate.to_check.length} เรื่องที่ต้องตรวจ/แก้ใน Viswalk (บันทึกเป็น checklist ข้างไฟล์ .inpx)`
      : 'สร้างไฟล์ได้ · ยังต้องตรวจผลใน Viswalk ก่อนใช้งาน';
  buildViswalkBtn.disabled = !gate.passed || validationBusy || buildBusy;
}

function renderValidation(result) {
  currentValidation = result;
  document.getElementById('buildSection').classList.remove('hidden');
  const counts = result.severity_counts || {};
  document.getElementById('buildErrors').textContent = counts.error ?? 0;
  document.getElementById('buildWarnings').textContent = counts.warning ?? 0;
  document.getElementById('buildInfo').textContent = counts.info ?? 0;
  document.getElementById('buildStatus').textContent = result.build_allowed ? 'ตรวจแล้ว · สร้างได้' : 'สร้างไม่ได้';

  const root = document.getElementById('buildIssueList');
  root.innerHTML = '';
  if (!(result.issues || []).length) {
    const item = document.createElement('div');
    item.className = 'build-issue info';
    item.textContent = 'ตรวจสอบผ่าน ไม่พบปัญหา';
    root.appendChild(item);
    return;
  }

  // Grouped by what the Engine found (UX-02): one row per kind with a count,
  // opening to the objects; raw technical text stays in each object line.
  const groups = new Map();
  for (const issue of result.issues || []) {
    const key = `${issue.severity || 'warning'}|${issue.type || 'issue'}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(issue);
  }
  const sevOrder = { error: 0, warning: 1, info: 2 };
  const ordered = [...groups.entries()].sort(([a, x], [b, y]) =>
    (sevOrder[a.split('|')[0]] ?? 3) - (sevOrder[b.split('|')[0]] ?? 3) || y.length - x.length);
  for (const [key, issues] of ordered) {
    const [severity, type] = key.split('|');
    const row = document.createElement('details');
    row.className = `issue-group ${severity}`;
    const head = document.createElement('summary');
    const sev = document.createElement('span');
    sev.className = `issue-sev ${severity}`;
    sev.textContent = { error: 'ข้อผิดพลาด', warning: 'คำเตือน', info: 'ข้อมูล' }[severity] || severity;
    const title = document.createElement('strong');
    title.textContent = ENGINE_ISSUE_TH[type] || type;
    const count = document.createElement('span');
    count.className = 'gate-count';
    count.textContent = issues.length;
    head.append(sev, title, count);
    row.appendChild(head);
    if (issues[0].rationale) {
      const why = document.createElement('small');
      why.className = 'gate-detail';
      why.textContent = issues[0].rationale;
      row.appendChild(why);
    }
    row.addEventListener('toggle', () => {
      if (!row.open || row.querySelector('.gate-items')) return;
      const list = document.createElement('ul');
      list.className = 'gate-items';
      for (const issue of issues.slice(0, ITEMS_SHOWN)) {
        const li = document.createElement('li');
        const label = document.createElement('span');
        label.className = 'gate-item-label';
        const names = issue.names ? issue.names.join(' ↔ ') : (issue.name || '');
        const where = issue.level_key != null ? levelNameOf(issue.level_key) : '';
        const extra = issue.overlap_area_m2 != null ? `ซ้อน ${issue.overlap_area_m2} ตร.ม.`
          : issue.outside_area_m2 != null ? `นอกพื้นที่เดิน ${issue.outside_area_m2} ตร.ม.` : '';
        label.textContent = [names, where, extra].filter(Boolean).join(' · ') || JSON.stringify(issue);
        li.appendChild(label);
        list.appendChild(li);
      }
      if (issues.length > ITEMS_SHOWN) {
        const li = document.createElement('li');
        li.className = 'gate-items-more';
        li.textContent = `และอีก ${issues.length - ITEMS_SHOWN} รายการ · ครบใน "รายงานการตรวจ"`;
        list.appendChild(li);
      }
      row.appendChild(list);
    });
    root.appendChild(row);
  }
}


function renderBuildResult(payload) {
  const result = payload.result || payload;
  currentBuild = result;
  document.getElementById('buildSection').classList.remove('hidden');
  if (payload.validation) renderValidation(payload.validation);
  document.getElementById('buildStatus').textContent = 'สำเร็จ';
  document.getElementById('buildDuration').textContent = result.duration_sec != null ? `${result.duration_sec}s` : '—';
  const path = document.getElementById('buildOutputPath');
  path.classList.remove('hidden');
  path.textContent = `ไฟล์ผลลัพธ์: ${result.output_path || result.output_filename || 'สร้างโมเดล Viswalk แล้ว'}`;
  setBuildOutputReady(true);
  document.getElementById('stepBuild').classList.add('done');
}

validateBtn.addEventListener('click', async () => {
  validateBtn.disabled = true;
  validateBtn.setAttribute('aria-busy', 'true');
  validationBusy = true;
  setMessage('กำลังตรวจโมเดลคนเดินด้วย Geometry Engine v0.3...');
  try {
    const result = await api('/api/validate', { method: 'POST' });
    renderValidation(result);
    const gate = await refreshGate();
    dock.select((result.severity_counts?.error || 0) ? 'build' : 'checks');
    buildViswalkBtn.disabled = !(gate && gate.passed);
    const c = result.severity_counts || {};
    // "Engine passed" is not "model verified" (UX-01): say which one this is.
    setMessage((c.error || 0)
      ? `ตรวจ Geometry: Engine สร้างไฟล์จากโมเดลนี้ไม่ได้ (${c.error} ข้อผิดพลาด) · ดูแท็บผล Engine`
      : `ตรวจ Geometry: Engine สร้างไฟล์ได้` +
        (gate && gate.to_check?.length ? ` · ยังมี ${gate.to_check.length} เรื่องต้องตรวจใน Viswalk` : '') +
        ' · ยังไม่ใช่การรับรองโมเดล');
  } catch (error) {
    setMessage(`ตรวจ Geometry ไม่สำเร็จ: ${error.message}`);
  } finally {
    validationBusy = false;
    validateBtn.disabled = false;
    validateBtn.removeAttribute('aria-busy');
    buildViswalkBtn.disabled = !(currentGate && currentGate.passed) || buildBusy;
  }
});

function confirmBuild(checks) {
  // Resolves true to build, false to go back to the list. Native <dialog>:
  // focus is trapped while open and Esc closes it.
  const dialog = document.getElementById('buildConfirm');
  document.getElementById('buildConfirmLead').textContent =
    `Geometry Engine สร้างไฟล์ได้ · มี ${checks.length} เรื่องที่ต้องตรวจหรือแก้ใน Viswalk หลังสร้างไฟล์`;
  const list = document.getElementById('buildConfirmList');
  list.innerHTML = '';
  const shown = checks.slice(0, 6);
  for (const item of shown) {
    const li = document.createElement('li');
    const title = document.createElement('span');
    title.textContent = item.title;
    const count = document.createElement('strong');
    count.textContent = item.count;
    li.append(title, count);
    list.appendChild(li);
  }
  if (checks.length > shown.length) {
    const li = document.createElement('li');
    li.textContent = `และอีก ${checks.length - shown.length} เรื่อง (ดูในแท็บ "รายการตรวจ")`;
    list.appendChild(li);
  }
  return new Promise(resolve => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'build'), { once: true });
    dialog.returnValue = '';
    dialog.showModal();
    document.getElementById('buildConfirmGo').focus();
  });
}

// ---------------------------------------------------------------------------
// Live build progress: the build request blocks until Vissim has saved the
// file, so the panel polls /api/build/progress while it runs.
// ---------------------------------------------------------------------------
const jobPanel = (() => {
  const panel = document.getElementById('jobPanel');
  const stagesEl = document.getElementById('jobStages');
  let timer = null;
  const clock = sec => `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, '0')}`;

  function render(p) {
    const stages = p.stages || [];
    if (stagesEl.childElementCount !== stages.length) {
      stagesEl.innerHTML = '';
      for (const [, label] of stages) {
        const li = document.createElement('li');
        li.textContent = label;
        stagesEl.appendChild(li);
      }
    }
    const idx = p.stage_index ?? 0;
    [...stagesEl.children].forEach((li, i) => {
      li.className = i < idx || p.result === 'success' ? 'done' : i === idx ? (p.result === 'failed' ? 'failed' : 'current') : '';
    });
    document.getElementById('jobElapsed').textContent = clock(p.elapsed_sec || 0);
    const counted = p.total ? ` ${p.done}/${p.total}` : '';
    const stageFrac = p.total ? Math.min(p.done / p.total, 1) : 0.5;
    const pct = p.result === 'success' ? 100 : Math.round(((idx + stageFrac) / Math.max(stages.length, 1)) * 100);
    document.getElementById('jobBar').style.width = `${pct}%`;
    const label = stages[idx]?.[1] || '';
    document.getElementById('jobDetail').textContent = p.result === 'failed'
      ? 'สร้างไฟล์ไม่สำเร็จ · ดูรายละเอียดในแถบสถานะด้านบน'
      : p.result === 'success'
        ? `เสร็จแล้ว · ใช้เวลา ${clock(p.elapsed_sec || 0)}`
        : `${label}${counted}${p.prog_id ? ` · ${p.prog_id}` : ''}${p.fallback ? ' · เปลี่ยนไปใช้ Vissim รุ่นถัดไป' : ''}`;
    document.getElementById('jobTitle').textContent = p.result === 'success' ? 'สร้างไฟล์ Viswalk แล้ว'
      : p.result === 'failed' ? 'สร้างไฟล์ไม่สำเร็จ' : 'กำลังสร้างไฟล์ Viswalk';
    panel.dataset.state = p.result || 'running';
  }

  async function poll() {
    try { render(await api('/api/build/progress')); } catch { /* keep the last view */ }
  }

  return {
    start() {
      panel.classList.remove('hidden');
      panel.dataset.state = 'running';
      render({ stages: [], stage_index: 0, elapsed_sec: 0 });
      clearInterval(timer);
      poll();
      timer = setInterval(poll, 700);
    },
    async stop() {
      clearInterval(timer);
      await poll();
      setTimeout(() => panel.classList.add('hidden'), panel.dataset.state === 'success' ? 4000 : 8000);
    },
  };
})();

buildViswalkBtn.addEventListener('click', async () => {
  const checks = (currentGate?.items || []).filter(i => i.policy === 'check');
  if (checks.length && !(await confirmBuild(checks))) {
    dock.select('checks');
    return;
  }
  buildBusy = true;
  buildViswalkBtn.disabled = true;
  buildViswalkBtn.setAttribute('aria-busy', 'true');
  validateBtn.disabled = true;
  setBuildOutputReady(false);
  document.getElementById('buildSection').classList.remove('hidden');
  document.getElementById('buildStatus').textContent = 'กำลังสร้าง...';
  document.getElementById('buildDuration').textContent = '—';
  setMessage('กำลังสร้างไฟล์ Viswalk · Vissim อาจเปิดขึ้นชั่วครู่ แล้วโปรแกรมจะบันทึกและปิดให้เอง');
  jobPanel.start();
  try {
    const result = await api('/api/build-vissim', { method: 'POST' });
    renderBuildResult(result);
    dock.select('build');
    setMessage(`สร้างไฟล์ Viswalk สำเร็จ: ${result.result?.output_filename || 'ไฟล์ .inpx'} · เปิดตรวจผลใน Vissim ก่อนใช้งาน`);
  } catch (error) {
    document.getElementById('buildStatus').textContent = 'ไม่สำเร็จ';
    setMessage(`สร้างไฟล์ Viswalk ไม่สำเร็จ: ${error.message}`);
  } finally {
    jobPanel.stop();
    buildViswalkBtn.removeAttribute('aria-busy');
    buildBusy = false;
    validateBtn.disabled = false;
    buildViswalkBtn.disabled = !(currentGate && currentGate.passed);
  }
});

downloadInpxTopBtn.addEventListener('click', () => startDownload('/api/build/latest/download'));
downloadInpxBtn.addEventListener('click', () => startDownload('/api/build/latest/download'));
downloadBuildReportBtn.addEventListener('click', () => startDownload('/api/build/latest/report'));
downloadValidationBtn.addEventListener('click', () => startDownload('/api/build/latest/validation'));
downloadBuildLogBtn.addEventListener('click', () => startDownload('/api/build/latest/log'));
openBuildFolderBtn.addEventListener('click', async () => {
  openBuildFolderBtn.disabled = true;
  try {
    const result = await api('/api/build/latest/open-folder', { method: 'POST' });
    setMessage(`เปิดโฟลเดอร์ผลลัพธ์แล้ว: ${result.folder}`);
  } catch (error) {
    setMessage(`เปิดโฟลเดอร์ผลลัพธ์ไม่สำเร็จ: ${error.message}`);
  } finally {
    openBuildFolderBtn.disabled = false;
  }
});

// Which installed Vissim builds the file (engine menu). "อัตโนมัติ" = newest,
// falling back to the next release if that one will not start.
async function renderVissimChoice() {
  const row = document.getElementById('vissimChoiceRow');
  const select = document.getElementById('vissimChoice');
  let info;
  try { info = await api('/api/vissim'); } catch { return; }
  const releases = info.registered || [];
  row.classList.toggle('hidden', !releases.length);
  if (!releases.length) return;
  select.innerHTML = '';
  const auto = new Option(`อัตโนมัติ (รุ่นใหม่สุด: ${releases[0]})`, '');
  select.appendChild(auto);
  for (const r of releases) {
    select.appendChild(new Option(`Vissim ${r}`, String(r)));
  }
  select.value = info.choice ? String(info.choice) : '';
  select.disabled = !!info.fixed_by_environment;
  select.title = info.fixed_by_environment ? 'กำหนดด้วย VBB_VISSIM_PROGID ตอนเปิดแอป' : '';
}

document.getElementById('vissimChoice').addEventListener('change', async event => {
  const value = event.target.value;
  try {
    await api('/api/vissim', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ release: value ? Number(value) : null }),
    });
    setMessage(value ? `สร้างไฟล์ด้วย Vissim ${value}` : 'สร้างไฟล์ด้วย Vissim รุ่นใหม่สุดที่ติดตั้ง (ถ้าเปิดไม่ได้จะลองรุ่นถัดไป)');
  } catch (error) {
    setMessage(`เปลี่ยนรุ่น Vissim ไม่สำเร็จ: ${error.message}`);
    renderVissimChoice();
  }
});

async function restoreState() {
  try {
    const [health, state] = await Promise.all([
      api('/api/health'),
      api('/api/project'),
    ]);

    document.getElementById('healthText').textContent = health.ifcopenshell
      ? `Python ${health.python} · IfcOpenShell ${health.ifcopenshell} · Three ${health.three_vendor_ready ? 'ready' : 'missing'} · Build ${health.vissim_engine_found && health.base_network_found && health.build_adapter_found ? 'ready' : 'missing'}`
      : `Python ${health.python} · IfcOpenShell missing`;
    document.getElementById('versionText').textContent = health.app_version
      ? `แอป v${health.app_version} · Semantic schema ${health.semantic_schema_version} · ${health.engine_contract} · ` +
        (health.vissim_prog_id
          ? `Vissim ที่จะใช้: ${health.vissim_prog_id}${health.vissim_release_tested === false ? ' (รุ่นนี้ยังไม่ได้ทดสอบ build จริง)' : ''}`
          : 'ไม่พบ Vissim ในเครื่อง (ยังตรวจและเตรียมโมเดลได้)')
      : '';
    if (health.app_version) document.getElementById('appVersionText').textContent = `v${health.app_version}`;
    renderVissimChoice();
    if (health.credit) document.getElementById('creditText').textContent = health.credit;

    if (!health.three_vendor_ready) {
      setMessage('ไม่พบไฟล์ Three.js · รัน install.bat ก่อนใช้งานมุมมอง 3D');
    }

    selectionState = state.selection || { mode: 'auto', overrides: {} };

    if (state.upload) {
      analyzeBtn.disabled = false;
      document.getElementById('fileMeta').textContent =
        `${state.upload.original_name} · ${formatBytes(state.upload.size_bytes)} · นำเข้าแล้ว`;
    }

    if (state.analysis?.kind === 'ifc') {
      currentAudit = state.analysis;
      renderAudit(currentAudit);
      load3dBtn.disabled = false;
      document.getElementById('stepAnalyze').classList.add('done');
    }

    if (state.geometry?.status === 'loaded') {
      generateSemanticBtn.disabled = false;
    }

    if (state.semantic?.status === 'ready') {
      try {
        currentSemantic = await api('/api/ifc/semantic?draft=1');
        renderSemanticSummary(currentSemantic);
        setExportReady(!state.semantic.stale);
        if (!state.semantic.stale) document.getElementById('stepSemantic').classList.add('done');
      } catch (error) {
        setMessage(`โหลดโมเดลคนเดินเดิมไม่สำเร็จ: ${error.message}`);
      }
    }


    // Reopen the 3D workspace the way it was left: source model, then the
    // pedestrian-model preview if a current (non-stale) one exists.
    if (currentAudit && health.three_vendor_ready && state.geometry?.status === 'loaded') {
      const loaded = await runLoad3d();
      if (loaded && currentSemantic && state.semantic?.status === 'ready' && !state.semantic.stale) {
        try {
          const v = await waitForViewer();
          if (typeof v.loadSemantic === 'function' && Number(v.loadSemantic(currentSemantic) || 0) > 0) {
            v.setMode('simulation');
            setViewerBadge('simulation');
            setActiveModeButton('simulationModeBtn');
          }
        } catch (error) {
          // The preview is a convenience on reload; the model itself is restored.
        }
      }
      if (loaded) setMessage('เปิดโครงการเดิมแล้ว · โหลดโมเดล 3D กลับมาตามสถานะล่าสุด');
    }

    if (state.build?.validation) {
      renderValidation(state.build.validation);
      if (state.semantic?.status === 'ready' && !state.semantic.stale) await refreshGate();
    }
    if (state.build?.status === 'success' && state.build?.result) {
      renderBuildResult({ result: state.build.result, validation: state.build.validation });
    }
  } catch (error) {
    setMessage(`ตรวจความพร้อมตอนเริ่มโปรแกรมไม่สำเร็จ: ${error.message}`);
  }
}

restoreState();
