// IFC Relay UI - Build: live progress, results and downloads, Vissim release choice, restoring state on start.
// Classic script loaded after app.js (shared globals; order set in index.html).

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
      document.getElementById('jobCloseBtn')?.classList.add('hidden');
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
      // Success fades; a failure stays until the engineer closes it (UX-22).
      if (panel.dataset.state === 'success') setTimeout(() => panel.classList.add('hidden'), 4000);
      else document.getElementById('jobCloseBtn')?.classList.remove('hidden');
    },
  };
})();

document.getElementById('jobCloseBtn')?.addEventListener('click', () => {
  document.getElementById('jobPanel').classList.add('hidden');
});

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
