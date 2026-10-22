// IFC Relay UI - Pedestrian model: object inspector, model summary and connectivity note, preparing the model (manual and automatic).
// Classic script loaded after app.js (shared globals; order set in index.html).

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

// Stair/ramp units and the engineer's decisions. The state is never shown as
// "0 stairs" when it is only unknown (loading or failed) (UX-04).
let stairOverview = null;
let stairState = 'unknown';         // unknown | loading | ready | error
let stairBusy = false;

function renderStairOverview(overview, state = overview ? 'ready' : stairState) {
  stairOverview = overview || stairOverview;
  stairState = state;
  const counts = stairState === 'ready' ? (stairOverview?.counts || {}) : null;
  const show = v => (counts ? String(v ?? 0) : stairState === 'loading' ? '…' : '–');
  document.getElementById('stairUnits').textContent = show(counts?.units);
  document.getElementById('stairIncluded').textContent = show(counts?.include);
  document.getElementById('stairReview').textContent = show(counts?.review);
  const btn = document.getElementById('stairBulkBtn');
  if (btn) {
    btn.disabled = stairBusy || stairState === 'loading' || (stairState === 'ready' && !counts.review);
    btn.textContent = stairBusy ? 'กำลังนำเข้าบันได…'
      : stairState === 'loading' ? 'กำลังอ่านรายการบันได…'
      : stairState === 'error' ? 'อ่านรายการบันไดไม่สำเร็จ · ลองใหม่'
      : 'นำเข้าบันไดทั้งหมด…';
    btn.classList.toggle('needs-action', stairState === 'ready' && counts.review > 0);
  }
  document.getElementById('stairResetBtn')?.classList.toggle('hidden', !(counts && counts.include));
  // Pending decisions are visible next to "prepare", not only at the bottom of the left panel (UX-02).
  const chip = document.getElementById('stairPendingChip');
  if (chip) {
    const pending = counts ? counts.review : 0;
    chip.classList.toggle('hidden', !pending);
    chip.textContent = pending ? `บันได ${pending} ชุดยังไม่ได้นำเข้า` : '';
  }
}

async function refreshStairOverview() {
  renderStairOverview(null, 'loading');
  try {
    renderStairOverview(await api('/api/stairs'), 'ready');
  } catch (error) {
    renderStairOverview(null, 'error');
    setMessage(`อ่านรายการบันไดไม่สำเร็จ: ${error.message} · กดปุ่มในบล็อก "บันไดและทางลาด" เพื่อลองใหม่`);
  }
}

function showStairBlock() {
  const block = document.getElementById('stairReviewBlock');
  if (!block) return;
  block.scrollIntoView({ block: 'center', behavior: 'smooth' });
  block.classList.remove('flash');
  void block.offsetWidth;                 // restart the highlight
  block.classList.add('flash');
  document.getElementById('stairBulkBtn')?.focus({ preventScroll: true });
}
document.getElementById('stairPendingChip')?.addEventListener('click', showStairBlock);

// Before preparing: units still in review will not be in the model. Asked once per
// pending count, so re-preparing does not nag; "include" applies the bulk action first.
let stairSkipAcknowledged = null;
async function confirmStairsBeforePrepare() {
  const pending = stairState === 'ready' ? stairOverview?.counts?.review || 0 : 0;
  if (!pending || stairSkipAcknowledged === pending) return true;
  const dialog = document.getElementById('stairPrepareConfirm');
  if (!dialog) return true;
  document.getElementById('stairPrepareLead').textContent =
    `IFC มีบันได/ทางลาด ${stairOverview.counts.units} ชุด · ยังไม่ได้นำเข้า ${pending} ชุด · ถ้าเตรียมต่อ โมเดลคนเดินรอบนี้จะไม่มีบันไดเหล่านี้`;
  const choice = await new Promise(resolve => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue), { once: true });
    dialog.returnValue = '';
    dialog.showModal();
    document.getElementById('stairPrepareInclude').focus();
  });
  if (choice === 'include') return runStairBulk('include');
  if (choice === 'skip') {
    stairSkipAcknowledged = pending;
    return true;
  }
  return false;                           // Esc: nothing happens
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
  if (stairBusy) return;
  if (stairState !== 'ready') {
    await refreshStairOverview();
    if (stairState !== 'ready') return;
  }
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

// Bulk include with a visible busy state; a second click while it runs does nothing (UX-03).
async function runStairBulk(status) {
  if (stairBusy) return false;
  stairBusy = true;
  renderStairOverview(null, stairState);
  const confirmBtn = document.getElementById('stairConfirmBtn');
  if (confirmBtn) confirmBtn.disabled = true;
  const started = Date.now();
  const tick = setInterval(() => setMessage(
    `${status === 'include' ? 'กำลังนำเข้าบันได/ทางลาด' : 'กำลังคืนสถานะบันได'} · ${Math.round((Date.now() - started) / 1000)} วิ`), 1000);
  try {
    const result = await applyStairBulk(status);
    setMessage(status === 'include'
      ? `นำเข้าบันได/ทางลาดแล้ว ${result.overview.counts.include} ชุด · กด "เตรียมโมเดลคนเดิน" เพื่อดูลูกศรทิศขึ้นใน 3D`
      : 'คืนบันได/ทางลาดทั้งหมดเป็น "รอตรวจสอบ" แล้ว');
    return true;
  } catch (error) {
    setMessage(`${status === 'include' ? 'นำเข้าบันได' : 'คืนสถานะบันได'}ไม่สำเร็จ: ${error.message}`);
    return false;
  } finally {
    clearInterval(tick);
    stairBusy = false;
    if (confirmBtn) confirmBtn.disabled = false;
    renderStairOverview(null, stairState);
  }
}

document.getElementById('stairConfirmBtn')?.addEventListener('click', async () => {
  hideStairConfirm();
  await runStairBulk('include');
});

document.getElementById('stairResetBtn')?.addEventListener('click', () => runStairBulk('auto'));

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
  const exits = Object.keys(con.anchors || {}).length;
  const basis = con.basis === 'anchors'
    ? `วัดจากทางออกที่กำหนด ${exits} จุด`
    : (exits ? 'ทางออกที่วาดไม่แตะพื้นที่เดิน · วัดจากโครงข่ายใหญ่ที่สุดแทน' : 'วัดจากโครงข่ายใหญ่ที่สุด · วาด "ทางออก" บนแปลนเพื่อวัดจากทางออกจริง');
  note.className = `connectivity-note ${ok ? 'ok' : 'warn'}`;
  note.textContent = ok
    ? `ตรวจการเชื่อมต่อทางเรขาคณิต: พื้นที่เดินต่อถึงกันหมด · บันไดเชื่อม ${con.stairs_linked} ตัว · ${basis} (ยังไม่ใช่การตรวจเส้นทางเดินใน Viswalk)`
    : `ตรวจการเชื่อมต่อทางเรขาคณิต: พื้นที่ที่เดินไปไม่ถึง ${iso.length} แห่ง (${Number(con.isolated_area_m2).toFixed(1)} ตร.ม., แสดงเป็นสีแดงใน 3D) · ${basis}` +
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

// UX-02: plan edits re-prepare the model by themselves once drawing pauses. The
// edit is drawn (and a passage's wall cuts marked) at once; the authoritative
// model replaces that preview when the run finishes.
const AUTO_PREPARE_KEY = 'ifcrelay.autoPrepare';
const AUTO_PREPARE_DELAY = 1200;
const autoPrepareBtn = document.getElementById('autoPrepareBtn');
const autoPrepareOn = () => autoPrepareBtn.getAttribute('aria-pressed') === 'true';
try { autoPrepareBtn.setAttribute('aria-pressed', String(localStorage.getItem(AUTO_PREPARE_KEY) !== '0')); } catch { /* storage blocked */ }
autoPrepareBtn.addEventListener('click', () => {
  const on = !autoPrepareOn();
  autoPrepareBtn.setAttribute('aria-pressed', String(on));
  try { localStorage.setItem(AUTO_PREPARE_KEY, on ? '1' : '0'); } catch { /* storage blocked */ }
  setMessage(on ? 'เปิดการเตรียมโมเดลคนเดินใหม่อัตโนมัติหลังแก้แปลน' : 'ปิดการเตรียมใหม่อัตโนมัติ · กด "เตรียมโมเดลคนเดินใหม่" เองหลังแก้แปลน');
  if (on && generateSemanticBtn.dataset.step === 'stale') scheduleAutoPrepare();
});
let autoPrepareTimer = null;
let autoPrepareQueued = false;
let preparing = false;

function scheduleAutoPrepare() {
  if (!autoPrepareOn()) return;
  clearTimeout(autoPrepareTimer);
  autoPrepareTimer = setTimeout(runAutoPrepare, AUTO_PREPARE_DELAY);
}

function runAutoPrepare() {
  if (!autoPrepareOn()) return;
  if (pendingShape || viewer()?.planHasFirstPoint?.()) { scheduleAutoPrepare(); return; }   // still drawing
  if (preparing || generateSemanticBtn.disabled) { autoPrepareQueued = true; return; }
  prepareModel({ auto: true });
}

generateSemanticBtn.addEventListener('click', async () => {
  if (await confirmStairsBeforePrepare()) prepareModel();
});

async function prepareModel({ auto = false } = {}) {
  if (preparing) return;
  preparing = true;
  clearTimeout(autoPrepareTimer);
  document.getElementById('staleBanner').classList.toggle('auto', auto);
  generateSemanticBtn.disabled = true;
  generateSemanticBtn.setAttribute('aria-busy', 'true');
  setMessage(auto ? 'กำลังเตรียมโมเดลคนเดินใหม่อัตโนมัติจากการแก้ไขบนแปลน...'
    : 'กำลังเตรียมโมเดลคนเดิน: รวมพื้นที่เดิน แปลงผนังและช่องเปิดตามองค์ประกอบที่เลือก...');
  try {
    const result = await api('/api/ifc/semantic', { method: 'POST' });
    currentSemantic = result.model;
    currentValidation = null;
    currentBuild = null;
    renderSemanticSummary(result);
    if (!auto) dock.select('details', { open: false });   // counts update; the viewer keeps its size
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
    document.getElementById('staleBanner').classList.remove('auto');
    preparing = false;
    if (autoPrepareQueued) { autoPrepareQueued = false; scheduleAutoPrepare(); }
  }
}

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
