// IFC Relay UI - BIM tree: loaded IFC elements by storey -> IFC class -> element.
// Classic script loaded after app.js (shared globals; order set in index.html).
// Groups fill only when opened, so a large model costs nothing until it is browsed.

const TREE_PAGE = 200;
const TREE_STATUS_TH = { include: 'นำเข้า', review: 'รอตรวจสอบ', exclude: 'ไม่ใช้' };

function renderModelTree() {
  const root = document.getElementById('modelTree');
  const tree = viewer()?.sourceTree?.();
  if (!root || !tree) return;
  // Re-rendered when more of the model loads: keep what the engineer had open.
  const reopen = new Set([...root.querySelectorAll('details[open]')].map(d => d.dataset.key));
  root.innerHTML = '';
  if (!tree.size) {
    root.innerHTML = '<div class="tree-empty">โครงสร้างจะแสดงหลังเปิดโมเดล 3D</div>';
    return;
  }
  // Storeys in the IFC's elevation order, then any others (e.g. unassigned).
  const order = (currentAudit?.spatial?.storeys || []).map(s => s.name);
  const storeys = [...tree.keys()].sort((a, b) => {
    const ia = order.indexOf(a), ib = order.indexOf(b);
    return (ia < 0 ? 1e9 : ia) - (ib < 0 ? 1e9 : ib) || a.localeCompare(b);
  });
  for (const storey of storeys) {
    const types = tree.get(storey);
    const total = [...types.values()].reduce((n, list) => n + list.length, 0);
    const node = treeNode('tree-storey', storey === 'Unassigned' ? 'ไม่ระบุชั้น' : storey, total);
    node.dataset.key = storey;
    node.addEventListener('toggle', () => {
      if (!node.open || node.dataset.filled) return;
      node.dataset.filled = '1';
      const body = node.querySelector('.tree-children');
      for (const [type, list] of [...types.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
        const group = treeNode('tree-type', type, list.length);
        group.dataset.key = `${storey}|${type}`;
        group.addEventListener('toggle', () => {
          if (group.open) fillTreeElements(group.querySelector('.tree-children'), storey, type);
        });
        body.appendChild(group);
        if (reopen.has(group.dataset.key)) group.open = true;
      }
    });
    root.appendChild(node);
    if (reopen.has(storey)) node.open = true;
  }
}

function treeNode(cls, label, count) {
  const node = document.createElement('details');
  node.className = `tree-node ${cls}`;
  const summary = document.createElement('summary');
  const name = document.createElement('span');
  name.className = 'tree-label';
  name.textContent = label;
  name.title = label;
  const n = document.createElement('span');
  n.className = 'check-count';
  n.textContent = count;
  summary.append(name, n);
  const children = document.createElement('div');
  children.className = 'tree-children';
  node.append(summary, children);
  return node;
}

// Refilled on every open: the status dots follow the latest include/exclude choices.
function fillTreeElements(body, storey, type, shown = TREE_PAGE) {
  const list = viewer()?.sourceTree?.().get(storey)?.get(type) || [];
  list.sort((a, b) => (a.name || a.guid).localeCompare(b.name || b.guid));
  body.innerHTML = '';
  for (const el of list.slice(0, shown)) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tree-element';
    button.title = `${el.name || type} · ${el.guid} · ${TREE_STATUS_TH[el.status] || el.status}`;
    const dot = document.createElement('i');
    dot.className = `tree-dot ${el.status}`;
    dot.setAttribute('aria-label', TREE_STATUS_TH[el.status] || el.status);
    const name = document.createElement('span');
    name.textContent = el.name || el.guid;
    button.append(dot, name);
    button.addEventListener('click', () => {
      document.getElementById('sourceModeBtn').click();
      viewer()?.showSource(el.guid);
      setMessage(`แสดง ${el.name || el.guid} ในโมเดลต้นฉบับ`);
    });
    body.appendChild(button);
  }
  if (list.length > shown) {
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'tree-more';
    more.textContent = `แสดงเพิ่ม (${Math.min(TREE_PAGE, list.length - shown)} จาก ${list.length - shown} ที่เหลือ)`;
    more.addEventListener('click', () => fillTreeElements(body, storey, type, shown + TREE_PAGE));
    body.appendChild(more);
  }
}
