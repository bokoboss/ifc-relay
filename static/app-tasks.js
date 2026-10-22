// IFC Relay UI - Work in progress: every heavy job (audit, 3D geometry, stairs,
// pedestrian model) shows what it is doing, whether it waits for memory, how
// long it has taken, and can be cancelled (review UX-05/06/21).
// Classic script loaded after app.js (shared globals; order set in index.html).

const taskPanel = (() => {
  const panel = document.getElementById('taskPanel');
  const list = document.getElementById('taskList');
  const local = new Map();          // work the browser waits for that is not a server job (e.g. validation)
  let serverJobs = [];
  let inFlight = 0;
  let timer = null;
  let nextId = 0;
  const clock = sec => `${Math.floor(sec / 60)}:${String(Math.floor(sec % 60)).padStart(2, '0')}`;
  const STATE_TH = { queued: 'รอคิว · รอหน่วยความจำว่าง', running: 'กำลังทำ', cancelling: 'กำลังยกเลิก…' };

  function render() {
    const rows = [
      ...serverJobs.map(j => ({ key: j.id, title: j.title, state: STATE_TH[j.state] || j.state,
        elapsed: j.elapsed_sec, cancel: j.can_cancel ? j.id : null, queued: j.state === 'queued' })),
      ...[...local.values()].map(t => ({ key: `l${t.id}`, title: t.title, state: t.note || 'กำลังทำ',
        elapsed: (Date.now() - t.started) / 1000, cancel: null })),
    ];
    panel.classList.toggle('hidden', !rows.length);
    list.innerHTML = '';
    for (const r of rows) {
      const li = document.createElement('li');
      li.className = `task-row${r.queued ? ' queued' : ''}`;
      li.innerHTML = '<span class="job-spinner" aria-hidden="true"></span><span class="task-text"><strong></strong><small></small></span>' +
        '<span class="task-elapsed"></span>';
      li.querySelector('strong').textContent = r.title;
      li.querySelector('small').textContent = r.state;
      li.querySelector('.task-elapsed').textContent = clock(r.elapsed);
      if (r.cancel) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'task-cancel';
        b.textContent = 'ยกเลิก';
        b.addEventListener('click', async () => {
          b.disabled = true;
          try { await fetch(`/api/jobs/${encodeURIComponent(r.cancel)}/cancel`, { method: 'POST' }); } catch { /* ignore */ }
          poll();
        });
        li.appendChild(b);
      }
      list.appendChild(li);
    }
  }

  async function poll() {
    try {
      const res = await fetch('/api/jobs');
      serverJobs = res.ok ? (await res.json()).jobs || [] : [];
    } catch { serverJobs = []; }
    render();
    if (!inFlight && !serverJobs.length && !local.size) {
      clearInterval(timer);
      timer = null;
    }
  }

  function ensurePolling() {
    if (timer) return;
    timer = setInterval(poll, 1000);
    setTimeout(poll, 400);          // quick requests finish before anything shows
  }

  return {
    requestStarted() { inFlight += 1; ensurePolling(); },
    requestEnded() { inFlight = Math.max(0, inFlight - 1); },
    // Work the server does not list as a job: shown with elapsed time, no cancel.
    track(title, promise, note) {
      const id = ++nextId;
      local.set(id, { id, title, note, started: Date.now() });
      ensurePolling();
      render();
      return Promise.resolve(promise).finally(() => { local.delete(id); render(); });
    },
  };
})();
