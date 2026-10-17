import * as THREE from './vendor/three.module.js';
import { OrbitControls } from './vendor/jsm/controls/OrbitControls.js';

const host = document.getElementById('viewerCanvasHost');
const empty = document.getElementById('viewerEmpty');

if (!host) {
  throw new Error('viewerCanvasHost element not found.');
}

if (!window.WebGLRenderingContext) {
  throw new Error('WebGL is not available in this browser/session.');
}

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xe9eef2);

const camera = new THREE.PerspectiveCamera(48, 1, 0.01, 5000);
camera.position.set(18, 16, 18);

let renderer;
try {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
} catch (error) {
  throw new Error(`WebGLRenderer initialization failed: ${error?.message || error}`);
}
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
host.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.screenSpacePanning = true;
controls.target.set(0, 4, 0);

scene.add(new THREE.HemisphereLight(0xffffff, 0x617080, 1.35));
const sun = new THREE.DirectionalLight(0xffffff, 1.4);
sun.position.set(25, 35, 20);
scene.add(sun);

const grid = new THREE.GridHelper(120, 60, 0xa9b4bf, 0xd6dde3);
grid.material.transparent = true;
grid.material.opacity = 0.45;
scene.add(grid);

const modelGroup = new THREE.Group();
modelGroup.rotation.x = -Math.PI / 2;
scene.add(modelGroup);

const semanticGroup = new THREE.Group();
semanticGroup.rotation.x = -Math.PI / 2;
semanticGroup.visible = false;
scene.add(semanticGroup);

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
const meshes = new Map();
let selectionHelper = null;
let selectedGuid = null;
let mode = 'source';
let storeyFilter = new Set();
let categoryFilter = new Set();
let overrides = {};
let isolatedGuid = null;
let wireframe = false;
let semanticLoaded = false;
const semanticMeshes = [];

const sourceColors = {
  IfcWall: 0xc1c7cd,
  IfcWallStandardCase: 0xc1c7cd,
  IfcDoor: 0x8b633f,
  IfcWindow: 0x78a9d0,
  IfcSlab: 0xbec6b3,
  IfcColumn: 0xaeb2b6,
  IfcStair: 0xb3a78e,
  IfcStairFlight: 0xb3a78e,
  IfcRamp: 0xb3a78e,
  IfcRampFlight: 0xb3a78e,
  IfcRailing: 0x808b95,
  IfcRoof: 0xb78c8c,
};

const simulationColors = {
  obstacle: 0x555f68,
  walkable: 0x7fa9cc,
  wall_closure: 0x596b7c,
  vertical_connection: 0xb18a57,
  review: 0xc89a3d,
  none: 0x9ba4ad,
  opening: 0x63a86f,
};

function makeMaterial(item) {
  return new THREE.MeshStandardMaterial({
    color: sourceColors[item.ifc_type] ?? 0x9ba5ae,
    roughness: 0.82,
    metalness: 0.02,
    side: THREE.DoubleSide,
    transparent: item.ifc_type === 'IfcWindow' || item.ifc_type === 'IfcSlab',
    opacity: item.ifc_type === 'IfcWindow' ? 0.58 : item.ifc_type === 'IfcSlab' ? 0.75 : 1.0,
    wireframe: false,
  });
}


function disposeObjectTree(root) {
  root.traverse(object => {
    if (object.geometry) object.geometry.dispose?.();
    if (object.material) {
      if (Array.isArray(object.material)) object.material.forEach(m => m.dispose?.());
      else object.material.dispose?.();
    }
  });
}

function clearSemantic() {
  for (const child of [...semanticGroup.children]) {
    semanticGroup.remove(child);
    disposeObjectTree(child);
  }
  semanticMeshes.length = 0;
  semanticLoaded = false;
}

function shapeFromPolygon(points) {
  const shape = new THREE.Shape();
  if (!points?.length) return shape;
  shape.moveTo(Number(points[0][0]), Number(points[0][1]));
  for (let i = 1; i < points.length; i += 1) {
    shape.lineTo(Number(points[i][0]), Number(points[i][1]));
  }
  shape.closePath();
  return shape;
}

function semanticMaterial(color, opacity = 1) {
  return new THREE.MeshStandardMaterial({
    color,
    roughness: 0.86,
    metalness: 0.01,
    side: THREE.DoubleSide,
    transparent: opacity < 1,
    opacity,
  });
}

function levelZMap(model) {
  const map = new Map();
  for (const level of model.levels || []) map.set(Number(level.key), Number(level.z || 0));
  return map;
}

function addSemanticPreview(model) {
  clearSemantic();
  const levels = levelZMap(model);

  for (const area of model.areas || []) {
    if (!area.polygon?.length) continue;
    const geometry = new THREE.ShapeGeometry(shapeFromPolygon(area.polygon));
    const mesh = new THREE.Mesh(geometry, semanticMaterial(0x77a7c8, 0.56));
    mesh.position.z = (levels.get(Number(area.level_key)) || 0) + 0.012;
    mesh.userData.semantic = { kind: 'area', source: area };
    semanticGroup.add(mesh);
    semanticMeshes.push(mesh);
  }

  for (const wall of model.walls || []) {
    const sx = Number(wall.start?.[0]);
    const sy = Number(wall.start?.[1]);
    const ex = Number(wall.end?.[0]);
    const ey = Number(wall.end?.[1]);
    if (![sx, sy, ex, ey].every(Number.isFinite)) continue;
    const dx = ex - sx;
    const dy = ey - sy;
    const length = Math.hypot(dx, dy);
    if (length <= 1e-6) continue;
    const thickness = Math.max(Number(wall.thickness || 0.2), 0.01);
    const height = Math.max(Number(wall.height || 3.0), 0.02);
    const baseZ = (levels.get(Number(wall.level_key)) || 0) + Number(wall.z_offset || 0);
    const geometry = new THREE.BoxGeometry(length, thickness, height);
    const mesh = new THREE.Mesh(geometry, semanticMaterial(0x4f5962, 1));
    mesh.position.set((sx + ex) / 2, (sy + ey) / 2, baseZ + height / 2);
    mesh.rotation.z = Math.atan2(dy, dx);
    mesh.userData.semantic = { kind: 'wall', source: wall };
    semanticGroup.add(mesh);
    semanticMeshes.push(mesh);
  }

  for (const column of model.columns || []) {
    const cx = Number(column.center?.[0]);
    const cy = Number(column.center?.[1]);
    if (!Number.isFinite(cx) || !Number.isFinite(cy)) continue;
    const height = Math.max(Number(column.height || 3), 0.02);
    const baseZ = (levels.get(Number(column.level_key)) || 0) + Number(column.z_offset || 0);
    let geometry;
    if (column.shape === 'circle') {
      const radius = Math.max(Number(column.diameter || 0.5) / 2, 0.01);
      geometry = new THREE.CylinderGeometry(radius, radius, height, 24);
      geometry.rotateX(Math.PI / 2);
    } else {
      geometry = new THREE.BoxGeometry(
        Math.max(Number(column.width || 0.5), 0.01),
        Math.max(Number(column.depth || 0.5), 0.01),
        height,
      );
    }
    const mesh = new THREE.Mesh(geometry, semanticMaterial(0x606970, 1));
    mesh.position.set(cx, cy, baseZ + height / 2);
    if (column.shape !== 'circle') mesh.rotation.z = THREE.MathUtils.degToRad(Number(column.rotation_deg || 0));
    mesh.userData.semantic = { kind: 'column', source: column };
    semanticGroup.add(mesh);
    semanticMeshes.push(mesh);
  }

  for (const obstacle of model.obstacles || []) {
    if (!obstacle.polygon?.length) continue;
    const height = Math.max(Number(obstacle.height || 1.2), 0.02);
    const baseZ = (levels.get(Number(obstacle.level_key)) || 0) + Number(obstacle.z_offset || 0);
    const geometry = new THREE.ExtrudeGeometry(shapeFromPolygon(obstacle.polygon), {
      depth: height,
      bevelEnabled: false,
      steps: 1,
    });
    const mesh = new THREE.Mesh(geometry, semanticMaterial(0x69747c, 1));
    mesh.position.z = baseZ;
    mesh.userData.semantic = { kind: 'obstacle', source: obstacle };
    semanticGroup.add(mesh);
    semanticMeshes.push(mesh);
  }

  for (const connection of model.vertical_connections || []) {
    if (!connection.polygon?.length) continue;
    const startZ = (levels.get(Number(connection.start_level)) || 0) + Number(connection.start_z_offset || 0);
    const endZ = (levels.get(Number(connection.end_level)) ?? startZ) + Number(connection.end_z_offset || 0);
    let geometry;
    let mesh;
    if (connection.polygon_order === 'bottom_edge_first' && connection.polygon.length === 4) {
      // Sloped plane: first two points sit at the start height, last two at the end height.
      const p = connection.polygon;
      const zs = [startZ, startZ, endZ, endZ];
      geometry = new THREE.BufferGeometry();
      geometry.setAttribute('position', new THREE.Float32BufferAttribute(
        p.flatMap((pt, i) => [Number(pt[0]), Number(pt[1]), zs[i]]), 3,
      ));
      geometry.setIndex([0, 1, 2, 0, 2, 3]);
      geometry.computeVertexNormals();
      mesh = new THREE.Mesh(geometry, semanticMaterial(0xb18a57, 0.82));
    } else {
      geometry = new THREE.ShapeGeometry(shapeFromPolygon(connection.polygon));
      mesh = new THREE.Mesh(geometry, semanticMaterial(0xb18a57, 0.82));
      mesh.position.z = (startZ + endZ) / 2;
    }
    mesh.userData.semantic = { kind: 'vertical_connection', source: connection };
    semanticGroup.add(mesh);
    semanticMeshes.push(mesh);
  }

  semanticLoaded = semanticMeshes.length > 0;
}

function clearModel() {
  clearSemantic();
  if (selectionHelper) {
    scene.remove(selectionHelper);
    selectionHelper.geometry.dispose();
    selectionHelper.material.dispose();
    selectionHelper = null;
  }

  for (const mesh of meshes.values()) {
    modelGroup.remove(mesh);
    mesh.geometry.dispose();
    mesh.material.dispose();
  }
  meshes.clear();
  selectedGuid = null;
  isolatedGuid = null;
}

function effectiveStatus(item) {
  return overrides[item.global_id] || item.recommendation || 'review';
}

function itemPassesFilters(item) {
  const storeyKey = item.storey_name || 'Unassigned';
  if (storeyFilter.size && !storeyFilter.has(storeyKey)) return false;
  if (categoryFilter.size && !categoryFilter.has(item.ifc_type)) return false;
  if (isolatedGuid && item.global_id !== isolatedGuid) return false;
  return true;
}

function simulationVisible(item) {
  const status = effectiveStatus(item);
  if (item.simulation_role === 'opening') return false;
  if (item.simulation_role === 'wall_closure') return true;
  return status === 'include';
}

function updateMaterial(mesh) {
  const item = mesh.userData.item;
  if (!item) return;

  if (mode === 'source') {
    mesh.material.color.setHex(sourceColors[item.ifc_type] ?? 0x9ba5ae);
    mesh.material.opacity = item.ifc_type === 'IfcWindow' ? 0.58 : item.ifc_type === 'IfcSlab' ? 0.75 : 1.0;
    mesh.material.transparent = mesh.material.opacity < 1;
  } else {
    const role = item.simulation_role || 'review';
    mesh.material.color.setHex(simulationColors[role] ?? 0x8d979f);
    mesh.material.opacity = role === 'walkable' ? 0.62 : 1.0;
    mesh.material.transparent = mesh.material.opacity < 1;
  }

  mesh.material.wireframe = wireframe;
  mesh.material.needsUpdate = true;
}

function applyVisibility() {
  for (const mesh of meshes.values()) {
    const item = mesh.userData.item;
    let visible = itemPassesFilters(item);
    if (visible && mode === 'simulation') {
      visible = simulationVisible(item);
    }
    mesh.visible = visible;
    updateMaterial(mesh);
  }

  if (selectionHelper) {
    const mesh = selectedGuid ? meshes.get(selectedGuid) : null;
    selectionHelper.visible = !!mesh?.visible;
  }
}

function buildGeometry(item) {
  const positions = new Float32Array(item.vertices);
  const indexArray = item.indices.length > 65535
    ? new Uint32Array(item.indices)
    : new Uint16Array(item.indices);

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setIndex(new THREE.BufferAttribute(indexArray, 1));
  geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  return geometry;
}

function fitBox(box, padding = 1.25) {
  if (!box || box.isEmpty()) return;
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z, 1);
  const fov = THREE.MathUtils.degToRad(camera.fov);
  let distance = maxDim / (2 * Math.tan(fov / 2));
  distance *= padding;

  const direction = new THREE.Vector3(1, 0.72, 1).normalize();
  camera.position.copy(center).add(direction.multiplyScalar(distance));
  camera.near = Math.max(0.01, distance / 1000);
  camera.far = Math.max(500, distance * 20);
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.update();
}

function fitModel() {
  const box = new THREE.Box3();
  let any = false;

  if (mode === 'simulation' && semanticLoaded && semanticGroup.visible) {
    box.setFromObject(semanticGroup);
    any = !box.isEmpty();
  } else {
    for (const mesh of meshes.values()) {
      if (!mesh.visible) continue;
      box.expandByObject(mesh);
      any = true;
    }
  }

  if (any) fitBox(box, 1.35);
}

function fitSelection() {
  const mesh = selectedGuid ? meshes.get(selectedGuid) : null;
  if (!mesh) return;
  fitBox(new THREE.Box3().setFromObject(mesh), 2.1);
}

function selectGuid(guid, emit = true) {
  selectedGuid = guid || null;

  if (selectionHelper) {
    scene.remove(selectionHelper);
    selectionHelper.geometry.dispose();
    selectionHelper.material.dispose();
    selectionHelper = null;
  }

  const mesh = guid ? meshes.get(guid) : null;
  if (mesh) {
    selectionHelper = new THREE.BoxHelper(mesh, 0x1565c0);
    scene.add(selectionHelper);
    if (emit) {
      window.dispatchEvent(new CustomEvent('ifc-element-selected', {
        detail: mesh.userData.item,
      }));
    }
  }
}

function resize() {
  const width = Math.max(host.clientWidth, 1);
  const height = Math.max(host.clientHeight, 1);
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

function pointerSelect(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);

  const visibleMeshes = Array.from(meshes.values()).filter(mesh => mesh.visible);
  const hit = raycaster.intersectObjects(visibleMeshes, false)[0];
  if (hit?.object?.userData?.item?.global_id) {
    selectGuid(hit.object.userData.item.global_id, true);
  }
}

renderer.domElement.addEventListener('pointerup', pointerSelect);
window.addEventListener('resize', resize);

// Keep the renderer synchronized when a previously hidden explorer section
// becomes visible, when panels resize, or when the browser window changes.
const resizeObserver = new ResizeObserver(entries => {
  const entry = entries[0];
  if (!entry) return;
  const { width, height } = entry.contentRect;
  if (width < 2 || height < 2) return;
  resize();
});
resizeObserver.observe(host);

function animate() {
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}
resize();
animate();

window.IFCViewer = {
  load(payload, selectionOverrides = {}, options = {}) {
    const append = !!options.append;
    if (!append) clearModel();
    overrides = { ...selectionOverrides };

    for (const item of payload.elements || []) {
      if (!item.global_id || !item.vertices?.length || !item.indices?.length) continue;

      // Storey-lazy loading can request the same object twice. Keep one mesh per
      // GlobalId and replace stale geometry deterministically.
      const existing = meshes.get(item.global_id);
      if (existing) {
        modelGroup.remove(existing);
        existing.geometry.dispose();
        existing.material.dispose();
        meshes.delete(item.global_id);
      }

      const geometry = buildGeometry(item);
      const mesh = new THREE.Mesh(geometry, makeMaterial(item));
      mesh.userData.item = item;
      modelGroup.add(mesh);
      meshes.set(item.global_id, mesh);
    }

    const incomingStoreys = Object.keys(payload.storeys || {});
    const incomingCategories = Object.keys(payload.categories || {});
    storeyFilter = append
      ? new Set([...storeyFilter, ...incomingStoreys])
      : new Set(incomingStoreys);
    categoryFilter = append
      ? new Set([...categoryFilter, ...incomingCategories])
      : new Set(incomingCategories);

    isolatedGuid = null;
    mode = 'source';
    modelGroup.visible = true;
    semanticGroup.visible = false;
    applyVisibility();
    if (empty) empty.classList.add('hidden');

    resize();
    requestAnimationFrame(() => {
      resize();
      fitModel();
      requestAnimationFrame(resize);
    });
  },

  setMode(nextMode) {
    mode = nextMode === 'simulation' ? 'simulation' : 'source';
    const useSemantic = mode === 'simulation' && semanticLoaded;
    modelGroup.visible = !useSemantic;
    semanticGroup.visible = useSemantic;
    applyVisibility();
    if (selectionHelper) selectionHelper.visible = !useSemantic && !!meshes.get(selectedGuid)?.visible;
    requestAnimationFrame(() => { resize(); fitModel(); });
  },

  loadSemantic(model) {
    addSemanticPreview(model || {});
    if (mode === 'simulation') {
      modelGroup.visible = false;
      semanticGroup.visible = semanticLoaded;
      applyVisibility();
      requestAnimationFrame(() => { resize(); fitModel(); });
    }
    return semanticMeshes.length;
  },

  setFilters(storeys, categories) {
    storeyFilter = new Set(storeys || []);
    categoryFilter = new Set(categories || []);
    applyVisibility();
  },

  setOverrides(nextOverrides) {
    overrides = { ...(nextOverrides || {}) };
    applyVisibility();
  },

  selectByGuid(guid) {
    selectGuid(guid, true);
  },

  fitModel,
  fitSelection,

  isolateSelected() {
    if (!selectedGuid) return false;
    isolatedGuid = selectedGuid;
    applyVisibility();
    fitSelection();
    return true;
  },

  showAll() {
    isolatedGuid = null;
    applyVisibility();
    fitModel();
  },

  toggleWireframe() {
    wireframe = !wireframe;
    applyVisibility();
    return wireframe;
  },

  visibleGuids() {
    return Array.from(meshes.values())
      .filter(mesh => mesh.visible)
      .map(mesh => mesh.userData.item.global_id);
  },

  resize,

  diagnostics() {
    const gl = renderer.getContext();
    return {
      ready: true,
      hostWidth: host.clientWidth,
      hostHeight: host.clientHeight,
      canvasWidth: renderer.domElement.width,
      canvasHeight: renderer.domElement.height,
      meshCount: meshes.size,
      semanticMeshCount: semanticMeshes.length,
      webglVersion: gl instanceof WebGL2RenderingContext ? 2 : 1,
    };
  },
};

window.IFCViewerDiagnostics = window.IFCViewer.diagnostics();
window.dispatchEvent(new CustomEvent('ifc-viewer-ready', {
  detail: window.IFCViewerDiagnostics,
}));
