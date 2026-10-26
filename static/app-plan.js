// IFC Relay UI - 2D plan: tools, drawing with preview/confirm, undo/redo, the plan-edit list.
// Classic script loaded after app.js (shared globals; order set in index.html).

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
  exit: 'คลิกสองมุมทับพื้นที่ทางออก/จุดเริ่มเดิน · ใช้ตรวจว่าพื้นที่ไหนเดินไปไม่ถึง',
};
document.querySelectorAll('.plan-tool[data-tool]').forEach(button => {
  button.addEventListener('click', () => {
    planTool = button.dataset.tool;
    document.querySelectorAll('.plan-tool[data-tool]').forEach(b => b.classList.toggle('active', b === button));
    viewer()?.setPlanTool(planTool);
    document.getElementById('planHint').textContent = PLAN_HINTS[planTool] || '';
  });
});

window.addEventListener('plan-measure', event => {
  const { distance, final } = event.detail || {};
  document.getElementById('planHint').textContent = `ระยะ ${Number(distance).toFixed(2)} ม.${final ? '' : ' …'}`;
  if (final) setMessage(`วัดระยะบนแปลน: ${Number(distance).toFixed(3)} ม.`);
});

const EDIT_KIND_TH = { walkable: 'พื้นที่เดินเพิ่ม', obstacle: 'สิ่งกีดขวางเพิ่ม', passage: 'ทางผ่าน', exit: 'ทางออก' };
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
  saveHistory();
}

// Undo/redo survive a reload (per browser). Edits live on the server, so the
// saved history is replayed against the current edit list first; if it no
// longer fits (project reset, edits changed in another tab) it is dropped.
const HISTORY_KEY = 'ifcrelay.editHistory';
const HISTORY_MAX = 50;

function saveHistory() {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify({
      undo: editHistory.undo.slice(-HISTORY_MAX), redo: editHistory.redo.slice(-HISTORY_MAX),
    }));
  } catch { /* storage blocked: history stays in memory */ }
}

function editShape(edit) {
  return {
    polygon: (edit.polygon || []).map(point => [...point]),
    shape_type: edit.shape_type || 'polygon',
  };
}

function sameEditShape(a, b) {
  return JSON.stringify(editShape(a)) === JSON.stringify(editShape(b));
}

function historyFits(saved, edits) {
  // Replay each history stack in reverse to verify both presence and geometry.
  // Missing, reused or externally modified records invalidate old local history.
  const valid = step => step && ['add', 'delete', 'update'].includes(step.type)
    && step.edit?.uid && (step.type !== 'update' || (step.before?.polygon && step.after?.polygon));
  if (![...saved.undo, ...saved.redo].every(valid)) return false;
  const simulate = (stack, undo) => {
    const present = new Map(edits.map(edit => [edit.uid, edit]));
    for (const step of [...stack].reverse()) {
      const id = step.edit.uid;
      const current = present.get(id);
      if (step.type === 'add') {
        if (undo ? !current : !!current) return false;
        if (undo) present.delete(id); else present.set(id, step.edit);
      } else if (step.type === 'delete') {
        if (undo ? !!current : !current) return false;
        if (undo) present.set(id, step.edit); else present.delete(id);
      } else {
        if (!current || !sameEditShape(current, undo ? step.after : step.before)) return false;
        present.set(id, { ...current, ...editShape(undo ? step.before : step.after) });
      }
    }
    return true;
  };
  return simulate(saved.undo, true) && simulate(saved.redo, false);
}

let historyRestored = false;
function restoreHistory(edits) {
  if (historyRestored) return;
  historyRestored = true;
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(HISTORY_KEY) || 'null'); } catch { saved = null; }
  const ok = saved && Array.isArray(saved.undo) && Array.isArray(saved.redo) && historyFits(saved, edits);
  editHistory.undo = ok ? saved.undo : [];
  editHistory.redo = ok ? saved.redo : [];
  updateUndoButtons();
}

// A recreated edit gets a new ID/UID and a geometry update gets a new revision.
// Keep every history reference in sync without rewriting each step's before/after
// polygon snapshots, which are necessary to replay older updates correctly.
function remapEdit(oldEdit, newEdit) {
  for (const step of [...editHistory.undo, ...editHistory.redo]) {
    if (step.edit?.uid === oldEdit.uid) step.edit = newEdit;
  }
}

let editTransactionBusy = false;

function editFailureMessage(error, action) {
  const status = Number(error?.status || 0);
  if (status === 409) {
    return `${action}ไม่สำเร็จ: ข้อมูลถูกแก้ไขจากที่อื่นหรือ UID/Revision เปลี่ยน · โหลดรายการใหม่ก่อนแก้ไข (409)`;
  }
  if (status === 404) return `${action}ไม่สำเร็จ: ไม่พบรายการแก้ไขแล้ว (404)`;
  if (status === 400 || status === 422) return `${action}ไม่สำเร็จ: รูปทรงหรือข้อมูลไม่ถูกต้อง · ${error.message} (${status})`;
  return `${action}ไม่สำเร็จ: ${error.message}`;
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
  if (shape.tool === 'exit') {
    const floors = (currentSemantic?.areas || []).filter(a => Number(a.level_key) === Number(shape.level_key)
      && a.polygon && a.polygon.some((p, i, arr) => segmentHitsPolygon(p, arr[(i + 1) % arr.length], shape.polygon)
        || segmentHitsPolygon(shape.polygon[0], shape.polygon[0], a.polygon))).length;
    return `${label} ${area.toFixed(2)} ตร.ม. · ` + (floors ? 'ทับพื้นที่เดิน · ไม่เปลี่ยนรูปทรงโมเดล' : 'ไม่ทับพื้นที่เดินเลย');
  }
  return `${label} ${shape.polygon.length} มุม · ${area.toFixed(2)} ตร.ม.`;
}

async function saveEdit(shape, { record = true } = {}) {
  const result = await api('/api/edits', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      kind: shape.tool, level_key: shape.level_key, polygon: shape.polygon,
      ...(shape.shape_type ? { shape_type: shape.shape_type } : {}),
    }),
  });
  renderEdits(result.edits);
  markSemanticStale();
  scheduleAutoPrepare();
  if (record) {
    editHistory.undo.push({ type: 'add', edit: result.edit });
    editHistory.redo = [];
  }
  updateUndoButtons();
  return result.edit;
}

async function removeEdit(edit, { record = true } = {}) {
  if (!edit.uid) throw new Error('รายการนี้ไม่มี UID · โหลดข้อมูลล่าสุดก่อนลบ');
  const params = new URLSearchParams({
    expected_uid: edit.uid,
    expected_revision: String(edit.revision ?? 1),
  });
  const result = await api(`/api/edits/${encodeURIComponent(edit.id)}?${params}`, { method: 'DELETE' });
  renderEdits(result.edits);
  markSemanticStale();
  scheduleAutoPrepare();
  if (record) {
    editHistory.undo.push({ type: 'delete', edit });
    editHistory.redo = [];
  }
  updateUndoButtons();
}

const asShape = edit => ({
  tool: edit.kind, level_key: edit.level_key,
  polygon: edit.polygon, shape_type: edit.shape_type || 'polygon',
});

// Public internal helper for future B3/B4/B5 plan manipulation: one PATCH per
// committed geometry operation, exactly one undo transaction on real changes.
// Does NOT modify IFC / generated geometry and does not select/pick objects.
async function updateEditGeometry(edit, polygon, { shapeType = null, record = true } = {}) {
  if (!edit?.uid) throw new Error('รายการนี้ไม่มี UID · โหลดข้อมูลล่าสุดก่อนแก้ไข');
  const body = {
    expected_uid: edit.uid,
    expected_revision: edit.revision ?? 1,
    polygon,
  };
  if (shapeType != null && shapeType !== (edit.shape_type || 'polygon')) body.shape_type = shapeType;
  const result = await api(`/api/edits/${encodeURIComponent(edit.id)}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const changed = !sameEditShape(edit, result.edit);
  remapEdit(edit, result.edit);
  renderEdits(result.edits);
  if (changed) {
    markSemanticStale();
    scheduleAutoPrepare();
    if (record) {
      editHistory.undo.push({
        type: 'update', edit: result.edit,
        before: editShape(edit), after: editShape(result.edit),
      });
      editHistory.redo = [];
    }
  }
  updateUndoButtons();
  return result.edit;
}

async function undoEdit() {
  if (editTransactionBusy) return;
  const step = editHistory.undo.pop();
  if (!step) return;
  editTransactionBusy = true;
  try {
    if (step.type === 'add') {
      await removeEdit(step.edit, { record: false });
      editHistory.redo.push(step);
    } else if (step.type === 'delete') {
      const again = await saveEdit(asShape(step.edit), { record: false });
      remapEdit(step.edit, again);
      editHistory.redo.push({ type: 'delete', edit: again });
    } else if (step.type === 'update') {
      const again = await updateEditGeometry(step.edit, step.before.polygon, {
        shapeType: step.before.shape_type, record: false,
      });
      editHistory.redo.push({ ...step, edit: again });
    } else {
      throw new Error('ไม่รู้จักชนิดขั้นตอน Undo');
    }
    setMessage('ย้อนการแก้ไขแล้ว · กด "เตรียมโมเดลคนเดิน" อีกครั้งเพื่อใช้ผล');
  } catch (error) {
    editHistory.undo.push(step); // Failed transactions never consume history.
    setMessage(editFailureMessage(error, 'ย้อนการแก้ไข'));
  } finally {
    editTransactionBusy = false;
    updateUndoButtons();
  }
}

async function redoEdit() {
  if (editTransactionBusy) return;
  const step = editHistory.redo.pop();
  if (!step) return;
  editTransactionBusy = true;
  try {
    if (step.type === 'add') {
      const again = await saveEdit(asShape(step.edit), { record: false });
      remapEdit(step.edit, again);
      editHistory.undo.push({ type: 'add', edit: again });
    } else if (step.type === 'delete') {
      await removeEdit(step.edit, { record: false });
      editHistory.undo.push({ type: 'delete', edit: step.edit });
    } else if (step.type === 'update') {
      const again = await updateEditGeometry(step.edit, step.after.polygon, {
        shapeType: step.after.shape_type, record: false,
      });
      editHistory.undo.push({ ...step, edit: again });
    } else {
      throw new Error('ไม่รู้จักชนิดขั้นตอน Redo');
    }
    setMessage('ทำซ้ำแล้ว · กด "เตรียมโมเดลคนเดิน" อีกครั้งเพื่อใช้ผล');
  } catch (error) {
    editHistory.redo.push(step);
    setMessage(editFailureMessage(error, 'ทำซ้ำ'));
  } finally {
    editTransactionBusy = false;
    updateUndoButtons();
  }
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
      if (editTransactionBusy) return;
      editTransactionBusy = true;
      del.disabled = true;
      try {
        await removeEdit(edit);
        setMessage(`ลบ ${edit.id} แล้ว · กด "เตรียมโมเดลคนเดิน" อีกครั้งเพื่อใช้ผล (ย้อนได้)`);
      } catch (error) {
        setMessage(editFailureMessage(error, 'ลบ'));
      } finally {
        editTransactionBusy = false;
        del.disabled = false;
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
    const { edits } = await api('/api/edits');
    renderEdits(edits);
    restoreHistory(edits || []);
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
