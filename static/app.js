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
    setMessage(`3D viewer error: ${message}`);
    const status = document.getElementById('viewerStatus');
    if (status) status.textContent = `3D engine error: ${message}`;
  }
});

window.addEventListener('unhandledrejection', event => {
  const message = event.reason?.message || String(event.reason || 'Unknown module error');
  viewerRuntimeError = message;
  setMessage(`3D viewer module error: ${message}`);
  const status = document.getElementById('viewerStatus');
  if (status) status.textContent = `3D module error: ${message}`;
});

function setMessage(text) {
  messageText.textContent = text;
}

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
  if (!response.ok) throw new Error(payload.detail || `HTTP ${response.status}`);
  return payload;
}

function viewer() {
  return window.IFCViewer || null;
}

function setExportReady(ready) {
  downloadSemanticTopBtn.disabled = !ready;
  downloadEngineTopBtn.disabled = !ready;
  validateBtn.disabled = !ready;
  buildViswalkBtn.disabled = !ready;
  if (!ready) setBuildOutputReady(false);
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
        setMessage(`3D viewer module error: ${message}`);
        const status = document.getElementById('viewerStatus');
        if (status) status.textContent = `3D module error: ${message}`;
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
  };
}

function updateLargeLoadControlState() {
  const value = geometryLoadMode?.value || 'simulation_all';
  const storeyMode = value.endsWith('_storey');
  if (geometryStoreySelect) geometryStoreySelect.disabled = !storeyMode;
  if (appendStoreyCheck) appendStoreyCheck.disabled = !storeyMode;
}

geometryLoadMode?.addEventListener('change', updateLargeLoadControlState);

fileInput.addEventListener('change', () => {
  selectedFile = fileInput.files?.[0] || null;
  uploadBtn.disabled = !selectedFile;
  document.getElementById('fileMeta').textContent = selectedFile
    ? `${selectedFile.name} · ${formatBytes(selectedFile.size)}`
    : 'No file imported';
});

uploadBtn.addEventListener('click', async () => {
  if (!selectedFile) return;
  uploadBtn.disabled = true;
  setMessage('Importing source model...');
  try {
    const form = new FormData();
    form.append('file', selectedFile);
    const result = await api('/api/import', { method: 'POST', body: form });
    document.getElementById('fileMeta').textContent =
      `${result.upload.original_name} · ${formatBytes(result.upload.size_bytes)} · imported`;
    analyzeBtn.disabled = false;
    load3dBtn.disabled = true;
    generateSemanticBtn.disabled = true;
    currentAudit = null;
    currentGeometry = null;
    currentSemantic = null;
    if (geometryStoreySelect) geometryStoreySelect.innerHTML = '';
    document.getElementById('largeModelSection')?.classList.add('hidden');
    setMessage('Import complete. Run Analyze.');
  } catch (error) {
    setMessage(`Import failed: ${error.message}`);
  } finally {
    uploadBtn.disabled = false;
  }
});

analyzeBtn.addEventListener('click', async () => {
  analyzeBtn.disabled = true;
  setMessage('Running IFC pre-flight audit...');
  try {
    const result = await api('/api/analyze', { method: 'POST' });
    if (result.kind !== 'ifc') {
      setMessage(result.message || 'Analysis complete.');
      return;
    }
    currentAudit = result;
    renderAudit(result);
    load3dBtn.disabled = false;
    document.getElementById('stepAnalyze').classList.add('done');
    setMessage('IFC audit complete. Load the 3D model.');
  } catch (error) {
    setMessage(`Analysis failed: ${error.message}`);
  } finally {
    analyzeBtn.disabled = false;
  }
});

load3dBtn.addEventListener('click', async () => {
  load3dBtn.disabled = true;
  const request = geometryRequestFromControls();
  const subsetLabel = request.storey_ids.length
    ? `storey ${request.storey_ids[0]}`
    : 'whole model';
  setMessage(`Extracting ${request.mode} IFC geometry for ${subsetLabel}...`);

  try {
    const [geometry, selection] = await Promise.all([
      api('/api/ifc/geometry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
      }),
      api('/api/selection'),
    ]);

    if ((geometry.element_count || 0) === 0) {
      const selectedOption = geometryStoreySelect?.selectedOptions?.[0];
      const selectedLabel = selectedOption?.textContent || subsetLabel;
      document.getElementById('viewerStatus').textContent =
        `No 3D geometry in ${selectedLabel} for ${request.mode} mode.`;
      setMessage(
        `No 3D geometry found for ${selectedLabel}. ` +
        `Choose a storey with sim meshes, or switch to Full IFC mode.`
      );
      return;
    }

    currentGeometry = mergeGeometryPayload(currentGeometry, geometry, request.append);
    selectionState = selection;
    render3dFilters(currentGeometry);

    const explorerSection = document.getElementById('explorerSection');
    explorerSection.classList.remove('hidden');
    document.getElementById('viewerStatus').textContent = '3D engine readying canvas...';

    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));

    const v = await waitForViewer();
    v.load(geometry, selectionState.overrides || {}, { append: request.append });

    document.getElementById('viewerStatus').textContent =
      `${currentGeometry.element_count} loaded mesh elements · ${currentGeometry.triangle_count || 0} triangles · WebGL ready`;
    document.getElementById('previewNote').textContent = geometry.preview_note || '';

    const loadedText = document.getElementById('loadedSubsetText');
    if (loadedText) {
      const storeyText = Object.keys(currentGeometry.storeys || {}).join(', ') || 'Unassigned';
      loadedText.textContent = `Loaded subset: ${currentGeometry.element_count} elements · ${storeyText}`;
    }

    document.getElementById('stepExplore').classList.add('done');
    document.getElementById('stepSelect').classList.add('done');
    generateSemanticBtn.disabled = false;
    updateSelectionSummary();
    setMessage(
      request.append
        ? 'Storey appended to 3D view. Review selection or add another storey.'
        : 'Filtered 3D IFC loaded. Review selection, then Generate Semantic Model.'
    );
  } catch (error) {
    setMessage(`3D load failed: ${error.message}`);
  } finally {
    load3dBtn.disabled = false;
  }
});

resetBtn.addEventListener('click', async () => {
  try {
    await api('/api/project/reset', { method: 'POST' });
    window.location.reload();
  } catch (error) {
    setMessage(`Reset failed: ${error.message}`);
  }
});

function renderLargeModelPanel(result) {
  const panel = document.getElementById('largeModelSection');
  if (!panel) return;
  panel.classList.remove('hidden');

  const large = result.large_model || {};
  const counts = large.simulation_counts || {};
  document.getElementById('largeModelBadge').textContent = large.detected ? 'Large IFC detected' : 'Standard IFC';
  document.getElementById('largeFileSize').textContent = `${Number(large.file_size_mb || 0).toFixed(1)} MB`;
  document.getElementById('largeWalls').textContent = counts.walls ?? 0;
  document.getElementById('largeSlabs').textContent = counts.slabs ?? 0;
  document.getElementById('largeColumns').textContent = counts.columns ?? 0;
  document.getElementById('largeBeams').textContent = counts.beams_excluded ?? 0;
  document.getElementById('largeStairs').textContent =
    (counts.stairs ?? 0) + (counts.stair_flights ?? 0);

  document.getElementById('largeModelProfile').textContent = large.structural_like
    ? 'Structural-heavy IFC detected'
    : (large.detected ? 'Large multidisciplinary IFC' : 'Standard-size IFC');
  document.getElementById('largeModelNote').textContent = large.structural_like
    ? 'No architectural doors/windows were detected. Review openings before simulation. Beams stay excluded; floor slabs will be consolidated per storey.'
    : 'Browser loading can be filtered independently from the authoritative semantic build.';

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
      ? `${storey.name} · ${z} · ${meshCount} sim meshes`
      : `${storey.name} · ${z} · no simulation geometry`;
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
    div.textContent = 'No IFC audit warnings.';
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
  for (const [name, count] of Object.entries(geometry.storeys || {})) {
    storeyRoot.appendChild(makeCheckRow(name, count, true, checked => {
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

document.getElementById('sourceModeBtn').addEventListener('click', () => {
  viewer()?.setMode('source');
  document.getElementById('sourceModeBtn').classList.add('active');
  document.getElementById('simulationModeBtn').classList.remove('active');
  document.getElementById('stepPreview').classList.remove('done');
});

document.getElementById('simulationModeBtn').addEventListener('click', () => {
  viewer()?.setMode('simulation');
  document.getElementById('simulationModeBtn').classList.add('active');
  document.getElementById('sourceModeBtn').classList.remove('active');
  document.getElementById('stepPreview').classList.add('done');
  setMessage('Simulation Preview: door leaves hidden as pedestrian openings; windows shown as closure context.');
});

document.getElementById('fitModelBtn').addEventListener('click', () => viewer()?.fitModel());
document.getElementById('fitSelectionBtn').addEventListener('click', () => viewer()?.fitSelection());
document.getElementById('isolateBtn').addEventListener('click', () => {
  if (!viewer()?.isolateSelected()) setMessage('Select an IFC object before isolating.');
});
document.getElementById('showAllBtn').addEventListener('click', () => viewer()?.showAll());
document.getElementById('wireframeBtn').addEventListener('click', event => {
  const enabled = viewer()?.toggleWireframe();
  event.currentTarget.textContent = enabled ? 'Solid' : 'Wireframe';
});

window.addEventListener('ifc-element-selected', event => {
  selectedElement = event.detail;
  renderInspector(selectedElement);
});

function renderInspector(item) {
  if (!item) return;
  document.getElementById('emptyInspector').classList.add('hidden');
  document.getElementById('inspectorContent').classList.remove('hidden');
  document.getElementById('selectedName').textContent = item.name || item.ifc_type;
  document.getElementById('selectedType').textContent = item.ifc_type || '—';
  document.getElementById('selectedStorey').textContent = item.storey_name || 'Unassigned';
  document.getElementById('selectedGuid').textContent = item.global_id || '—';
  document.getElementById('selectedAuto').textContent = item.recommendation || 'review';
  document.getElementById('selectedMapping').textContent = item.viswalk_mapping || '—';
  document.getElementById('selectedRole').textContent = item.simulation_role || '—';

  const override = selectionState.overrides?.[item.global_id] || 'auto';
  const effective = effectiveStatus(item);
  document.getElementById('effectiveStatus').textContent =
    `Manual: ${override} · Effective: ${effective}`;

  document.querySelectorAll('.status-btn').forEach(button => {
    button.classList.toggle('active', button.dataset.status === override);
  });

  const note = document.getElementById('semanticNote');
  if (item.simulation_role === 'opening') {
    note.textContent = 'Door semantics: this element becomes a pedestrian opening, not a solid obstacle.';
  } else if (item.simulation_role === 'wall_closure') {
    note.textContent = 'Window semantics: excluded as a separate Vissim object, but kept visually as wall-closure context so it is not treated as a pedestrian opening.';
  } else {
    note.textContent = `Simulation mapping: ${item.viswalk_mapping || 'Review required'}`;
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
        enginePath.textContent = 'Selection changed. Semantic model is stale; generate it again before using engine output.';
      }
      setMessage(`${selectedElement.ifc_type} ${selectedElement.global_id}: ${status}`);
    } catch (error) {
      setMessage(`Selection update failed: ${error.message}`);
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
    `${summary.included_doors ?? 0} included door(s) → ${summary.door_openings_applied ?? 0} physical wall opening(s); ` +
    `openings without a door: ${summary.unfilled_openings_applied ?? 0} opened of ${summary.unfilled_openings ?? 0}; ` +
    `windows used as openings: ${summary.windows_used_as_openings ?? 0}.`;

  renderOpeningCandidates(
    result.model?.ifc_semantic?.opening_candidates || result.ifc_semantic?.opening_candidates || [],
  );

  const root = document.getElementById('semanticWarningList');
  root.innerHTML = '';
  if (!warnings.length) {
    const item = document.createElement('div');
    item.className = 'warning-item ok';
    item.textContent = 'Semantic extraction passed without warnings.';
    root.appendChild(item);
  } else {
    for (const warning of warnings) {
      const item = document.createElement('div');
      item.className = 'warning-item';
      item.textContent = warning;
      root.appendChild(item);
    }
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
  for (const c of ordered) {
    const row = document.createElement('label');
    row.className = 'check-row opening-row';
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = c.decision === 'include';
    input.disabled = !c.global_id;
    const text = document.createElement('span');
    const where = c.host_wall_name || c.host_wall_global_id || 'wall';
    text.textContent = `${where} · ${Number(c.width).toFixed(2)} × ${Number(c.height).toFixed(2)} m, sill ${Number(c.sill).toFixed(2)} m` +
      (c.level_key != null ? ` · level ${c.level_key}` : '');
    const tag = document.createElement('span');
    tag.className = `tag ${c.classification === 'passage_candidate' ? 'review' : 'exclude'}`;
    tag.textContent = c.classification === 'passage_candidate' ? 'passage?' : 'not walkable';
    input.addEventListener('change', async () => {
      input.disabled = true;
      try {
        await api('/api/selection', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ global_id: c.global_id, status: input.checked ? 'include' : 'auto' }),
        });
        c.decision = input.checked ? 'include' : 'auto';
        setMessage('Opening decision saved. Generate Semantic Model again to apply it.');
      } catch (error) {
        input.checked = !input.checked;
        setMessage(`Could not save opening decision: ${error.message}`);
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
  setMessage('Generating authoritative simulation-relevant geometry and consolidating floor slabs per storey...');
  try {
    const result = await api('/api/ifc/semantic', { method: 'POST' });
    currentSemantic = result.model;
    currentValidation = null;
    currentBuild = null;
    renderSemanticSummary(result);
    setExportReady(true);
    setBuildOutputReady(false);
    document.getElementById('stepSemantic').classList.add('done');

    const v = await waitForViewer();
    if (v.loadSemantic) {
      v.loadSemantic(result.model);
      v.setMode('simulation');
      document.getElementById('simulationModeBtn').classList.add('active');
      document.getElementById('sourceModeBtn').classList.remove('active');
      document.getElementById('stepPreview').classList.add('done');
    }

    const enginePath = document.getElementById('semanticEnginePath');
    enginePath.classList.remove('hidden');
    enginePath.textContent = 'Semantic model ready. Download JSON or save geometry_ifc_v03.json for Geometry Engine handoff.';
    setMessage('Semantic model generated. Simulation Preview now shows simplified engine-facing geometry.');
  } catch (error) {
    setMessage(`Semantic generation failed: ${error.message}`);
  } finally {
    generateSemanticBtn.disabled = false;
  }
});

downloadSemanticTopBtn.addEventListener('click', () => {
  if (!currentSemantic) return;
  startDownload('/api/ifc/semantic/download');
  setMessage('Downloading semantic JSON...');
});

downloadEngineTopBtn.addEventListener('click', () => {
  if (!currentSemantic) return;
  startDownload('/api/ifc/semantic/engine-download');
  setMessage('Downloading engine-ready geometry_ifc_v03.json...');
});

exportEngineBtn.addEventListener('click', async () => {
  exportEngineBtn.disabled = true;
  try {
    const result = await api('/api/ifc/semantic/export-engine-input', { method: 'POST' });
    const enginePath = document.getElementById('semanticEnginePath');
    enginePath.classList.remove('hidden');
    enginePath.textContent = `Saved: ${result.path}`;
    setMessage(result.note || 'Engine input exported.');
  } catch (error) {
    setMessage(`Engine input export failed: ${error.message}`);
  } finally {
    exportEngineBtn.disabled = false;
  }
});


function renderValidation(result) {
  currentValidation = result;
  document.getElementById('buildSection').classList.remove('hidden');
  const counts = result.severity_counts || {};
  document.getElementById('buildErrors').textContent = counts.error ?? 0;
  document.getElementById('buildWarnings').textContent = counts.warning ?? 0;
  document.getElementById('buildInfo').textContent = counts.info ?? 0;
  document.getElementById('buildStatus').textContent = result.build_allowed ? 'Validated' : 'Blocked';

  const root = document.getElementById('buildIssueList');
  root.innerHTML = '';
  if (!(result.issues || []).length) {
    const item = document.createElement('div');
    item.className = 'build-issue info';
    item.textContent = 'Validation passed with no issues.';
    root.appendChild(item);
    return;
  }

  for (const issue of result.issues || []) {
    const item = document.createElement('div');
    item.className = `build-issue ${issue.severity || 'warning'}`;
    const detail = issue.name || issue.type || 'Validation issue';
    const extra = issue.rationale || (issue.outside_area_m2 != null ? `Outside area: ${issue.outside_area_m2} m²` : '');
    item.innerHTML = `<strong>${escapeHtml((issue.severity || 'warning').toUpperCase())}</strong><span>${escapeHtml(detail)}</span><small>${escapeHtml(extra)}</small>`;
    root.appendChild(item);
  }
}

function renderBuildResult(payload) {
  const result = payload.result || payload;
  currentBuild = result;
  document.getElementById('buildSection').classList.remove('hidden');
  if (payload.validation) renderValidation(payload.validation);
  document.getElementById('buildStatus').textContent = 'SUCCESS';
  document.getElementById('buildDuration').textContent = result.duration_sec != null ? `${result.duration_sec}s` : '—';
  const path = document.getElementById('buildOutputPath');
  path.classList.remove('hidden');
  path.textContent = `Output: ${result.output_path || result.output_filename || 'Viswalk model built'}`;
  setBuildOutputReady(true);
  document.getElementById('stepBuild').classList.add('done');
}

validateBtn.addEventListener('click', async () => {
  validateBtn.disabled = true;
  setMessage('Validating semantic geometry with Geometry Engine v0.3...');
  try {
    const result = await api('/api/validate', { method: 'POST' });
    renderValidation(result);
    buildViswalkBtn.disabled = !result.build_allowed;
    const c = result.severity_counts || {};
    setMessage(`Validation complete: ${c.error || 0} error(s), ${c.warning || 0} warning(s), ${c.info || 0} info.`);
  } catch (error) {
    setMessage(`Validation failed: ${error.message}`);
  } finally {
    validateBtn.disabled = false;
  }
});

buildViswalkBtn.addEventListener('click', async () => {
  buildViswalkBtn.disabled = true;
  validateBtn.disabled = true;
  setBuildOutputReady(false);
  document.getElementById('buildSection').classList.remove('hidden');
  document.getElementById('buildStatus').textContent = 'Building...';
  document.getElementById('buildDuration').textContent = '—';
  setMessage('Building Viswalk model. Vissim 2025 may open briefly; the app will save and close it automatically.');
  try {
    const result = await api('/api/build-vissim', { method: 'POST' });
    renderBuildResult(result);
    setMessage(`BUILD SUCCESS: ${result.result?.output_filename || 'Viswalk .inpx created'}`);
  } catch (error) {
    document.getElementById('buildStatus').textContent = 'FAILED';
    setMessage(`Build failed: ${error.message}`);
  } finally {
    buildViswalkBtn.disabled = false;
    validateBtn.disabled = false;
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
    setMessage(`Opened output folder: ${result.folder}`);
  } catch (error) {
    setMessage(`Could not open output folder: ${error.message}`);
  } finally {
    openBuildFolderBtn.disabled = false;
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

    if (!health.three_vendor_ready) {
      setMessage('Three.js vendor files are missing. Run setup_app.ps1 before loading 3D.');
    }

    selectionState = state.selection || { mode: 'auto', overrides: {} };

    if (state.upload) {
      analyzeBtn.disabled = false;
      document.getElementById('fileMeta').textContent =
        `${state.upload.original_name} · ${formatBytes(state.upload.size_bytes)} · imported`;
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
        currentSemantic = await api('/api/ifc/semantic');
        renderSemanticSummary(currentSemantic);
        setExportReady(!state.semantic.stale);
        if (!state.semantic.stale) document.getElementById('stepSemantic').classList.add('done');
      } catch (error) {
        setMessage(`Semantic restore warning: ${error.message}`);
      }
    }


    if (state.build?.validation) {
      renderValidation(state.build.validation);
    }
    if (state.build?.status === 'success' && state.build?.result) {
      renderBuildResult({ result: state.build.result, validation: state.build.validation });
    }
  } catch (error) {
    setMessage(`Startup check failed: ${error.message}`);
  }
}

restoreState();
