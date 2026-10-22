// IFC Relay UI - Review queue: the before-build list, locating each item, the build confirmation.
// Classic script loaded after app.js (shared globals; order set in index.html).

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
    const result = await taskPanel.track('ตรวจ Geometry (Geometry Engine)', api('/api/validate', { method: 'POST' }));
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
