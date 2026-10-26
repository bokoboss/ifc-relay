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

// 2D plan view: top-down orthographic camera with pan/zoom only.
const orthoCamera = new THREE.OrthographicCamera(-10, 10, 10, -10, 0.01, 5000);
orthoCamera.up.set(0, 0, -1);              // IFC +y points up on screen
const planControls = new OrbitControls(orthoCamera, renderer.domElement);
planControls.enableRotate = false;
planControls.screenSpacePanning = true;
// In plan view LEFT drag on empty space pans, wheel zooms. B3 owns future
// manual-object drag capture; do not repurpose LEFT to rotate.
planControls.mouseButtons.LEFT = THREE.MOUSE.PAN;
planControls.mouseButtons.MIDDLE = THREE.MOUSE.DOLLY;
planControls.mouseButtons.RIGHT = THREE.MOUSE.PAN;
planControls.enabled = false;
let planActive = false;
let planLevelKey = null;
let planTool = 'select';
let planPoints = [];
let orthoHalfHeight = 10;
const activeCam = () => (planActive ? orthoCamera : camera);
const activeControls = () => (planActive ? planControls : controls);

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
let renderRequested = true;   // render on demand (see animate)
let lastRender = 0;
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

// Source meshes share materials (one per colour/opacity/state): thousands of
// elements with one material each made Chrome spend most of each frame on
// material switches. Flat shading needs no normals, so none are computed.
const sharedMaterials = new Map();

function sharedMaterial(color, opacity, depthWrite = true) {
  const key = `${color}|${opacity}|${depthWrite}|${wireframe}`;
  let material = sharedMaterials.get(key);
  if (!material) {
    material = new THREE.MeshStandardMaterial({
      color, roughness: 0.82, metalness: 0.02, side: THREE.DoubleSide, flatShading: true,
      transparent: opacity < 1, opacity, depthWrite, wireframe,
    });
    material.userData.shared = true;
    sharedMaterials.set(key, material);
  }
  return material;
}

function sourceOpacity(item) {
  return item.ifc_type === 'IfcWindow' ? 0.58 : item.ifc_type === 'IfcSlab' ? 0.75 : 1.0;
}

function makeMaterial(item) {
  return sharedMaterial(sourceColors[item.ifc_type] ?? 0x9ba5ae, sourceOpacity(item));
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

const ARROW_DERIVED = 0x1f8a70;   // up-direction derived from geometry (not yet certified in Vissim)
const ARROW_REVIEW = 0xd98e04;    // up-direction could not be determined reliably

function stairDirectionArrow(connection, startZ, endZ) {
  // Arrow from the true bottom edge to the true top edge, drawn just above the
  // sloped surface. Amber when the direction needs engineering review.
  const be = connection.bottom_edge;
  const te = connection.top_edge;
  if (!Array.isArray(be) || !Array.isArray(te) || be.length < 2 || te.length < 2) return null;
  const mid = (edge) => [(Number(edge[0][0]) + Number(edge[1][0])) / 2, (Number(edge[0][1]) + Number(edge[1][1])) / 2];
  const [bx, by] = mid(be);
  const [tx, ty] = mid(te);
  const lift = 0.25;
  const from = new THREE.Vector3(bx, by, startZ + lift);
  const to = new THREE.Vector3(tx, ty, endZ + lift);
  const dir = to.clone().sub(from);
  const length = dir.length();
  if (length < 0.2) return null;
  dir.normalize();
  const review = connection.direction_status !== 'derived_from_geometry';
  // Solid shaft + cone (WebGL lines are 1 px wide and hard to see).
  const color = review ? ARROW_REVIEW : ARROW_DERIVED;
  const material = new THREE.MeshBasicMaterial({ color, depthTest: false, transparent: true, opacity: 0.95 });
  const headLength = Math.min(0.9, Math.max(0.4, length * 0.2));
  const radius = 0.07;
  const arrow = new THREE.Group();
  const shaft = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, length - headLength, 10), material);
  shaft.position.y = (length - headLength) / 2;
  const cone = new THREE.Mesh(new THREE.ConeGeometry(radius * 3.2, headLength, 14), material);
  cone.position.y = length - headLength / 2;
  arrow.add(shaft, cone);
  arrow.position.copy(from);
  arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir);
  arrow.renderOrder = 10;
  arrow.userData.semantic = { kind: 'stair_direction', source: connection, review };
  return arrow;
}

function clearSemantic() {
  clearSemanticSelection();
  selectedSemantic = null;
  isolatedSemantic = null;
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

// Semantic level key -> IFC storey name, so the storey filter also applies to the
// pedestrian model. Generated landing levels (901+) have no storey of their own.
let semanticLevelNames = new Map();

function semanticLevelKey(info) {
  const src = info?.source || {};
  if (info?.kind === 'vertical_connection' || info?.kind === 'stair_direction') return Number(src.start_level);
  return Number(src.level_key);
}

let semanticLevelZ = new Map();

function semanticPassesFilters(object) {
  const info = object.userData.semantic;
  if (planActive && planLevelKey != null) {
    const src = info?.source || {};
    if (info?.kind === 'vertical_connection' || info?.kind === 'stair_direction') {
      return Number(src.start_level) === planLevelKey || Number(src.end_level) === planLevelKey;
    }
    return Number(src.level_key) === planLevelKey;
  }
  const name = semanticLevelNames.get(semanticLevelKey(info));
  return name == null || storeyFilter.has(name);
}

function addSemanticPreview(model) {
  clearSemantic();
  semanticWalls = Array.isArray(model.walls) ? model.walls : [];
  const levels = levelZMap(model);
  semanticLevelNames = new Map(
    (model.levels || []).filter(level => !level.generated && Number(level.key) < 900)
      .map(level => [Number(level.key), level.name]),
  );
  semanticLevelZ = levels;

  // Walking zones nobody can reach (connectivity check) - drawn red above the floor.
  for (const zone of model.ifc_semantic?.connectivity?.isolated_zones || []) {
    if (!zone.polygon?.length) continue;
    const geometry = new THREE.ShapeGeometry(shapeFromPolygon(zone.polygon));
    const mesh = new THREE.Mesh(geometry, semanticMaterial(0xc0392b, 0.38));
    mesh.position.z = (levels.get(Number(zone.level_key)) || 0) + 0.03;
    mesh.userData.semantic = { kind: 'isolated_zone', source: zone };
    semanticGroup.add(mesh);
    semanticMeshes.push(mesh);
  }

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

    const arrow = stairDirectionArrow(connection, startZ, endZ);
    if (arrow) semanticGroup.add(arrow);
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
    mesh.geometry.dispose();             // materials are shared and kept
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
  if (mode === 'overlay') {
    // Source IFC as a faint ghost behind the pedestrian model.
    mesh.material = sharedMaterial(sourceColors[item.ifc_type] ?? 0x9ba5ae, 0.16, false);
  } else if (mode === 'source') {
    mesh.material = sharedMaterial(sourceColors[item.ifc_type] ?? 0x9ba5ae, sourceOpacity(item));
  } else {
    const role = item.simulation_role || 'review';
    mesh.material = sharedMaterial(simulationColors[role] ?? 0x8d979f, role === 'walkable' ? 0.62 : 1.0);
  }
}

function applyVisibility() {
  requestRender();
  for (const mesh of meshes.values()) {
    const item = mesh.userData.item;
    let visible = itemPassesFilters(item);
    if (visible && mode === 'simulation') {
      visible = simulationVisible(item);
    }
    mesh.visible = visible;
    updateMaterial(mesh);
  }

  for (const child of semanticGroup.children) {
    if (child === semanticHelper) continue;
    if (child.userData?.semantic) {
      child.visible = semanticPassesFilters(child) && (!isolatedSemantic || child === isolatedSemantic);
      const mat = child.material;
      if (mat && 'wireframe' in mat) mat.wireframe = wireframe;
    }
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
  geometry.computeBoundingBox();         // no normals: shared materials use flat shading
  return geometry;
}

function fitBox(box, padding = 1.25) {
  requestRender();
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
  requestRender();
  if (planActive) {
    fitPlan();
    return;
  }
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

// The active selection follows the view: a pedestrian-model object while that
// model is shown, otherwise the source IFC element.
function activeSemanticSelection() {
  return semanticGroup.visible && selectedSemantic && selectedSemantic.parent === semanticGroup ? selectedSemantic : null;
}

function fitSelection() {
  requestRender();
  const sem = activeSemanticSelection();
  if (sem) {
    fitBox(new THREE.Box3().setFromObject(sem), 2.1);
    return;
  }
  const mesh = selectedGuid ? meshes.get(selectedGuid) : null;
  if (!mesh) return;
  fitBox(new THREE.Box3().setFromObject(mesh), 2.1);
}

function selectGuid(guid, emit = true) {
  requestRender();
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

let semanticHelper = null;

// ---------------------------------------------------------------------------
// 2D plan: drawing tools and engineer edits
// ---------------------------------------------------------------------------
const planOverlay = new THREE.Group();
planOverlay.rotation.x = -Math.PI / 2;
scene.add(planOverlay);
const editsGroup = new THREE.Group();
planOverlay.add(editsGroup);
const draftGroup = new THREE.Group();
planOverlay.add(draftGroup);
const focusGroup = new THREE.Group();     // "ดูตำแหน่ง" marker from the review queue
planOverlay.add(focusGroup);
const EDIT_COLORS = { walkable: 0x2e9e5b, obstacle: 0x34495e, passage: 0x0e9fb6, exit: 0xb86c4d, measure: 0xd35400 };
let manualEdits = [];
let selectedManualUid = null;
function markManualSelection(edit, emit = true) {
  selectedManualUid = edit?.uid || null;
  drawEdits();
  if (edit && emit) window.dispatchEvent(new CustomEvent('manual-edit-selected', {
    detail: { edit, origin: 'manual', level_key: edit.level_key },
  }));
  return !!edit;
}
let semanticWalls = [];            // centre-line walls of the model on screen (for the passage preview)

// UX-02: the part of a wall segment inside a polygon, as [t0, t1] pieces of the
// segment (0..1). Used to show where a passage will cut before the model is
// regenerated; once it is, the walls on screen are already cut and nothing shows.
function clipSegment(a, b, poly) {
  const ts = [0, 1];
  for (let i = 0; i < poly.length; i += 1) {
    const c = poly[i], d = poly[(i + 1) % poly.length];
    const r = [b[0] - a[0], b[1] - a[1]], q = [d[0] - c[0], d[1] - c[1]];
    const den = r[0] * q[1] - r[1] * q[0];
    if (Math.abs(den) < 1e-12) continue;
    const t = ((c[0] - a[0]) * q[1] - (c[1] - a[1]) * q[0]) / den;
    const u = ((c[0] - a[0]) * r[1] - (c[1] - a[1]) * r[0]) / den;
    if (t > 0 && t < 1 && u >= 0 && u <= 1) ts.push(t);
  }
  ts.sort((x, y) => x - y);
  const inside = (pt) => {
    let c = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i], [xj, yj] = poly[j];
      if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) c = !c;
    }
    return c;
  };
  const pieces = [];
  for (let i = 0; i + 1 < ts.length; i += 1) {
    const m = (ts[i] + ts[i + 1]) / 2;
    if (ts[i + 1] - ts[i] > 1e-6 && inside([a[0] + (b[0] - a[0]) * m, a[1] + (b[1] - a[1]) * m])) pieces.push([ts[i], ts[i + 1]]);
  }
  return pieces;
}

function passageCuts(edit) {
  const poly = edit.polygon.map(p => [Number(p[0]), Number(p[1])]);
  const cuts = [];
  for (const wall of semanticWalls) {
    if (Number(wall.level_key) !== Number(edit.level_key)) continue;
    const a = wall.start.map(Number), b = wall.end.map(Number);
    for (const [t0, t1] of clipSegment(a, b, poly)) {
      cuts.push({ wall, a: [a[0] + (b[0] - a[0]) * t0, a[1] + (b[1] - a[1]) * t0],
                  b: [a[0] + (b[0] - a[0]) * t1, a[1] + (b[1] - a[1]) * t1] });
    }
  }
  return cuts;
}

// The wall piece a passage will remove: a light band over the wall, wall-thick.
function cutMark(cut, z) {
  const dx = cut.b[0] - cut.a[0], dy = cut.b[1] - cut.a[1];
  const len = Math.hypot(dx, dy);
  const t = Math.max(Number(cut.wall.thickness || 0.2), 0.05) + 0.04;
  const nx = -dy / len * t / 2, ny = dx / len * t / 2;
  const mark = outline([[cut.a[0] + nx, cut.a[1] + ny], [cut.b[0] + nx, cut.b[1] + ny],
                  [cut.b[0] - nx, cut.b[1] - ny], [cut.a[0] - nx, cut.a[1] - ny]], z, 0xf4f7f8, 0.95);
  mark.children.forEach(c => { c.renderOrder += 3; });
  return mark;
}

function levelZ(key) {
  return semanticLevelZ.get(Number(key)) || 0;
}

function clearGroup(group) {
  requestRender();
  for (const child of [...group.children]) {
    group.remove(child);
    disposeObjectTree(child);
  }
}

function outline(points, z, color, fillOpacity = 0.28) {
  const group = new THREE.Group();
  const pts = points.map(p => new THREE.Vector3(Number(p[0]), Number(p[1]), z));
  const line = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(pts),
    new THREE.LineBasicMaterial({ color, depthTest: false }));
  line.renderOrder = 20;
  group.add(line);
  if (fillOpacity > 0 && points.length >= 3) {
    const fill = new THREE.Mesh(new THREE.ShapeGeometry(shapeFromPolygon(points)),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: fillOpacity, depthTest: false, side: THREE.DoubleSide }));
    fill.position.z = z;
    fill.renderOrder = 19;
    group.add(fill);
  }
  return group;
}

function drawEdits() {
  requestRender();
  clearGroup(editsGroup);
  for (const edit of manualEdits) {
    if (planActive && planLevelKey != null && Number(edit.level_key) !== planLevelKey) continue;
    const g = outline(edit.polygon, levelZ(edit.level_key) + 0.06,
      selectedManualUid === edit.uid ? 0xf49b31 : (EDIT_COLORS[edit.kind] || 0x888888),
      selectedManualUid === edit.uid ? 0.48 : 0.28);
    g.userData.edit = edit;
    if (edit.kind === 'passage') {
      for (const cut of passageCuts(edit)) {
        const mark = cutMark(cut, levelZ(edit.level_key) + 0.07);
        mark.userData.passagePreview = true;
        g.add(mark);
      }
    }
    editsGroup.add(g);
  }
}

function groundPoint(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, activeCam());
  const plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), -levelZ(planLevelKey));
  const hit = raycaster.ray.intersectPlane(plane, new THREE.Vector3());
  return hit ? [Math.round(hit.x * 1000) / 1000, Math.round(-hit.z * 1000) / 1000] : null;
}

function rectPoints(a, b) {
  return [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]], [a[0], b[1]]];
}

// ---- snapping ---------------------------------------------------------------
// Vertices and edges of the pedestrian model on the plan level (areas, walls,
// columns, obstacles, stairs, earlier edits). Cursor snaps to a vertex, else to
// the nearest point on an edge, within SNAP_PX screen pixels; Shift locks the
// segment to 0/90 degrees from the previous point.
const SNAP_PX = 12;
let planShape = 'rect';
let planCursor = null;
let snapVertices = [];
let snapSegments = [];
const snapMarker = new THREE.Mesh(new THREE.RingGeometry(0.06, 0.1, 20),
  new THREE.MeshBasicMaterial({ color: 0xd35400, depthTest: false, side: THREE.DoubleSide }));
snapMarker.renderOrder = 30;
snapMarker.visible = false;
planOverlay.add(snapMarker);

function rebuildSnapTargets() {
  snapVertices = [];
  snapSegments = [];
  if (!planActive) return;
  const ring = pts => {
    for (let i = 0; i < pts.length; i += 1) {
      const a = pts[i], b = pts[(i + 1) % pts.length];
      snapVertices.push([Number(a[0]), Number(a[1])]);
      snapSegments.push([[Number(a[0]), Number(a[1])], [Number(b[0]), Number(b[1])]]);
    }
  };
  for (const child of semanticGroup.children) {
    const info = child.userData?.semantic;
    if (!info || !child.visible) continue;
    const src = info.source || {};
    if (src.polygon) ring(src.polygon);
    if (src.start && src.end) {
      snapVertices.push(src.start, src.end);
      snapSegments.push([src.start, src.end]);
    }
    if (src.center) snapVertices.push(src.center);
  }
  for (const edit of manualEdits) if (Number(edit.level_key) === planLevelKey) ring(edit.polygon);
}

function metresPerPixel() {
  const rect = renderer.domElement.getBoundingClientRect();
  return ((orthoCamera.top - orthoCamera.bottom) / orthoCamera.zoom) / Math.max(rect.height, 1);
}

function snapPoint(raw, event) {
  if (!raw) return { point: null, kind: null };
  let p = raw;
  const tol = SNAP_PX * metresPerPixel();
  const last = planPoints[planPoints.length - 1];
  if (event?.shiftKey && last) {
    p = Math.abs(raw[0] - last[0]) >= Math.abs(raw[1] - last[1]) ? [raw[0], last[1]] : [last[0], raw[1]];
    return { point: p, kind: 'ortho' };
  }
  let best = null;
  let bestD = tol;
  for (const v of snapVertices) {
    const d = Math.hypot(v[0] - p[0], v[1] - p[1]);
    if (d < bestD) { best = [Number(v[0]), Number(v[1])]; bestD = d; }
  }
  if (best) return { point: best, kind: 'vertex' };
  for (const [a, b] of snapSegments) {
    const dx = b[0] - a[0], dy = b[1] - a[1];
    const len2 = dx * dx + dy * dy;
    if (len2 < 1e-9) continue;
    const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2));
    const q = [a[0] + t * dx, a[1] + t * dy];
    const d = Math.hypot(q[0] - p[0], q[1] - p[1]);
    if (d < bestD) { best = q; bestD = d; }
  }
  if (best) return { point: [Math.round(best[0] * 1000) / 1000, Math.round(best[1] * 1000) / 1000], kind: 'edge' };
  return { point: p, kind: null };
}

function polygonArea(pts) {
  let a = 0;
  for (let i = 0; i < pts.length; i += 1) {
    const [x1, y1] = pts[i], [x2, y2] = pts[(i + 1) % pts.length];
    a += x1 * y2 - x2 * y1;
  }
  return Math.abs(a) / 2;
}

function currentShape(cursor) {
  if (!planPoints.length || !cursor) return null;
  if (planTool === 'measure') return [planPoints[0], cursor];
  if (planShape === 'rect') return rectPoints(planPoints[0], cursor);
  return [...planPoints, cursor];
}

function emitDraft(cursor, snapKind) {
  const last = planPoints[planPoints.length - 1];
  const shape = currentShape(cursor);
  window.dispatchEvent(new CustomEvent('plan-draft', {
    detail: {
      tool: planTool,
      shape: planShape,
      snap: snapKind,
      vertices: planPoints.length,
      segment: last && cursor ? Math.hypot(cursor[0] - last[0], cursor[1] - last[1]) : null,
      width: planShape === 'rect' && last && cursor ? Math.abs(cursor[0] - planPoints[0][0]) : null,
      depth: planShape === 'rect' && last && cursor ? Math.abs(cursor[1] - planPoints[0][1]) : null,
      area: shape && shape.length >= 3 ? polygonArea(shape) : null,
    },
  }));
}

function drawDraft(cursor, snapKind = null) {
  requestRender();
  clearGroup(draftGroup);
  const z = levelZ(planLevelKey) + 0.08;
  snapMarker.visible = !!(cursor && snapKind && snapKind !== 'ortho');
  if (snapMarker.visible) snapMarker.position.set(cursor[0], cursor[1], z + 0.01);
  if (!planPoints.length || !cursor) return;
  const color = planTool === 'measure' ? EDIT_COLORS.measure : (EDIT_COLORS[planTool] || 0x888888);
  const shape = currentShape(cursor);
  if (planTool === 'measure' || (planShape === 'poly' && shape.length < 3)) {
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(shape.map(p => new THREE.Vector3(p[0], p[1], z))),
      new THREE.LineBasicMaterial({ color, depthTest: false }));
    line.renderOrder = 21;
    draftGroup.add(line);
  } else {
    draftGroup.add(outline(shape, z, color, 0.18));
  }
  if (planTool === 'measure') {
    window.dispatchEvent(new CustomEvent('plan-measure', {
      detail: { distance: Math.hypot(cursor[0] - planPoints[0][0], cursor[1] - planPoints[0][1]), final: false },
    }));
  } else {
    emitDraft(cursor, snapKind);
  }
}

function finishShape(polygon) {
  planPoints = [];
  clearGroup(draftGroup);
  if (!polygon || polygon.length < 3 || polygonArea(polygon) < 0.01) return;
  window.dispatchEvent(new CustomEvent('plan-shape', {
    detail: { tool: planTool, level_key: planLevelKey, polygon,
      shape_type: planShape === 'rect' ? 'rectangle' : 'polygon' },
  }));
}

function planClick(event) {
  const { point: p } = snapPoint(groundPoint(event), event);
  if (!p) return;
  if (planTool === 'measure' || planShape === 'rect') {
    if (!planPoints.length) {
      planPoints = [p];
      return;
    }
    const a = planPoints[0];
    if (planTool === 'measure') {
      planPoints = [];
      clearGroup(draftGroup);
      window.dispatchEvent(new CustomEvent('plan-measure', {
        detail: { distance: Math.hypot(p[0] - a[0], p[1] - a[1]), final: true, from: a, to: p },
      }));
      return;
    }
    if (Math.abs(p[0] - a[0]) < 0.05 || Math.abs(p[1] - a[1]) < 0.05) return;
    finishShape(rectPoints(a, p));
    return;
  }
  // free polygon: clicking the first vertex again closes it
  if (planPoints.length >= 3) {
    const first = planPoints[0];
    if (Math.hypot(p[0] - first[0], p[1] - first[1]) <= SNAP_PX * metresPerPixel()) {
      lastPolygonClosure = { time: performance.now(), x: event.clientX, y: event.clientY };
      finishShape([...planPoints]);
      return;
    }
  }
  planPoints.push(p);
  drawDraft(p);
}

function fitPlan() {
  requestRender();
  const box = new THREE.Box3();
  for (const child of semanticGroup.children) {
    if (child.visible && child.userData?.semantic) box.expandByObject(child);
  }
  if (box.isEmpty()) box.setFromObject(semanticGroup);
  if (box.isEmpty()) return;
  const centre = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  const rect = renderer.domElement.getBoundingClientRect();
  const aspect = Math.max(rect.width, 1) / Math.max(rect.height, 1);
  orthoHalfHeight = Math.max(size.z / 2, size.x / 2 / aspect, 2) * 1.12;
  orthoCamera.zoom = 1;
  orthoCamera.position.set(centre.x, levelZ(planLevelKey) + 200, centre.z);
  planControls.target.set(centre.x, levelZ(planLevelKey), centre.z);
  orthoCamera.lookAt(planControls.target);
  resize();
  planControls.update();
}

function clearSemanticSelection() {
  if (!semanticHelper) return;
  scene.remove(semanticHelper);
  semanticHelper.geometry.dispose();
  semanticHelper.material.dispose();
  semanticHelper = null;
}

// Source GlobalIds a pedestrian-model object came from (areas merge many slabs).
function semanticSourceGuids(info) {
  const src = info?.source || {};
  const guids = [];
  if (src.ifc_global_id) guids.push(src.ifc_global_id);
  for (const g of src.ifc_source_global_ids || []) if (!guids.includes(g)) guids.push(g);
  if (src.ifc_parent_global_id && !guids.includes(src.ifc_parent_global_id)) guids.push(src.ifc_parent_global_id);
  return guids;
}

let selectedSemantic = null;
let isolatedSemantic = null;

function selectSemantic(object) {
  clearSemanticSelection();
  selectedSemantic = object || null;
  if (!object) return;
  semanticHelper = new THREE.BoxHelper(object, 0xd98e04);
  scene.add(semanticHelper);
  const info = object.userData.semantic;
  const guids = semanticSourceGuids(info);
  window.dispatchEvent(new CustomEvent('semantic-element-selected', {
    detail: {
      kind: info.kind,
      source: info.source,
      sourceGuids: guids,
      sourceItems: guids.map(g => meshes.get(g)?.userData.item).filter(Boolean),
    },
  }));
}

function resize() {
  requestRender();
  const width = Math.max(host.clientWidth, 1);
  const height = Math.max(host.clientHeight, 1);
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
  const aspect = width / height;
  orthoCamera.left = -orthoHalfHeight * aspect;
  orthoCamera.right = orthoHalfHeight * aspect;
  orthoCamera.top = orthoHalfHeight;
  orthoCamera.bottom = -orthoHalfHeight;
  orthoCamera.updateProjectionMatrix();
}

function pointerSelect(event) {
  const rect = renderer.domElement.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, activeCam());

  // U1 selection: manual edits take precedence at the active plan level.
  // Raycast their filled footprint and border; never turn a source IFC or
  // generated semantic mesh into an editable manual item.
  if (planActive && editsGroup.visible) {
    const hits = raycaster.intersectObjects(editsGroup.children, true);
    for (const hit of hits) {
      let candidate = hit.object;
      while (candidate && !candidate.userData?.edit) candidate = candidate.parent;
      const edit = candidate?.userData?.edit;
      if (edit && Number(edit.level_key) === planLevelKey) {
        markManualSelection(edit);
        return;
      }
    }
  }

  if (semanticGroup.visible) {
    const targets = semanticGroup.children.filter(child => child.visible
      && child.userData?.semantic && child !== semanticHelper);
    const owners = raycaster.intersectObjects(targets, true).map(hit => {
      let object = hit.object;
      while (object && !object.userData?.semantic) object = object.parent;
      return object;
    }).filter(Boolean);
    const object = owners.find(o => o.userData.semantic.kind !== 'area') || owners[0];
    if (object) { selectSemantic(object); return; }
  }

  // Overlay mode also permits inspecting a visible IFC source-only object.
  if (!modelGroup.visible) return;
  const visibleMeshes = Array.from(meshes.values()).filter(mesh => mesh.visible);
  const hit = raycaster.intersectObjects(visibleMeshes, false)[0];
  if (hit?.object?.userData?.item?.global_id) selectGuid(hit.object.userData.item.global_id, true);
}

// Ignore drags (orbit/pan): select only on a click that did not move.
let pointerDownAt = null;
let lastPolygonClosure = null;
let recentPolygonClicks = [];
renderer.domElement.addEventListener('pointerdown', event => {
  pointerDownAt = event.button === 0 ? [event.clientX, event.clientY] : null;
});
renderer.domElement.addEventListener('pointerup', event => {
  if (event.button !== 0 || !pointerDownAt) return;
  const down = pointerDownAt;
  pointerDownAt = null;
  if (Math.hypot(event.clientX - down[0], event.clientY - down[1]) > 5) return;
  if (planActive && planTool !== 'select') {
    if (planShape === 'poly') {
      recentPolygonClicks.push({ x: event.clientX, y: event.clientY, time: performance.now() });
      if (recentPolygonClicks.length > 2) recentPolygonClicks.shift();
      if (lastPolygonClosure
          && performance.now() - lastPolygonClosure.time < 450
          && Math.hypot(event.clientX - lastPolygonClosure.x,
                        event.clientY - lastPolygonClosure.y) < 5) return;
    }
    lastPolygonClosure = null;
    // Never suppress a normal polygon vertex merely because clicks are rapid.
    planClick(event);
    return;
  }
  pointerSelect(event);
});
renderer.domElement.addEventListener('pointercancel', () => { pointerDownAt = null; });
renderer.domElement.addEventListener('pointermove', event => {
  if (!planActive || planTool === 'select') return;
  const { point, kind } = snapPoint(groundPoint(event), event);
  planCursor = point;
  drawDraft(point, kind);
});
renderer.domElement.addEventListener('dblclick', event => {
  if (!planActive || planTool === 'select' || planShape !== 'poly') return;
  // A fast run of DIFFERENT clicks on one canvas may still emit dblclick in
  // Chromium. Require the last two pointerup events to occupy the SAME
  // screen position, otherwise this is an ordinary continued polygon.
  if (recentPolygonClicks.length !== 2) return;
  const [first, second] = recentPolygonClicks;
  if (second.time - first.time > 600
      || Math.hypot(first.x - second.x, first.y - second.y) > 4) return;
  event.preventDefault();
  recentPolygonClicks = [];
  // The two raw screen clicks represent one intended vertex. Their snapped
  // model coordinates may differ, so remove the second by EVENT identity,
  // not by geometry distance.
  if (planPoints.length >= 4) planPoints.pop();
  if (planPoints.length >= 3) finishShape([...planPoints]);
  else if (lastPolygonClosure) {
    planPoints = [];
    clearGroup(draftGroup);
  }
});
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

// Render on demand: a frame is drawn when the camera moves or something may have
// changed (any input, a load, a resize), plus once a second as a safety net. A
// large model drawn 60 times a second kept Chrome busy even when nothing moved.
function requestRender() {
  renderRequested = true;
}
for (const c of [controls, planControls]) c.addEventListener('change', requestRender);
for (const type of ['pointerdown', 'pointermove', 'pointerup', 'wheel', 'keydown', 'click', 'input', 'change']) {
  window.addEventListener(type, requestRender, { passive: true, capture: true });
}

function animate(time = 0) {
  const moved = activeControls().update();
  if (moved || renderRequested || time - lastRender > 1000) {
    renderRequested = false;
    lastRender = time;
    renderer.render(scene, activeCam());
  }
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

    if (options.keepView) {
      // Background addition: keep the mode, camera and selection as they are.
      applyVisibility();
      return;
    }
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
    requestRender();
    mode = ['simulation', 'overlay'].includes(nextMode) ? nextMode : 'source';
    const useSemantic = mode !== 'source' && semanticLoaded;
    modelGroup.visible = mode !== 'simulation' || !semanticLoaded;
    semanticGroup.visible = useSemantic;
    applyVisibility();
    if (selectionHelper) selectionHelper.visible = !useSemantic && !!meshes.get(selectedGuid)?.visible;
    if (semanticHelper) semanticHelper.visible = useSemantic;
    requestAnimationFrame(() => { resize(); fitModel(); });
  },

  loadSemantic(model) {
    requestRender();
    addSemanticPreview(model || {});
    drawEdits();
    if (planActive) requestAnimationFrame(() => rebuildSnapTargets());
    if (mode === 'simulation' || mode === 'overlay') {
      modelGroup.visible = mode === 'overlay';
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

  // ---- 2D plan -------------------------------------------------------------
  enterPlan(levelKey) {
    requestRender();
    if (!semanticLoaded) return false;
    planActive = true;
    planLevelKey = Number(levelKey);
    planPoints = [];
    controls.enabled = false;
    planControls.enabled = true;
    this.setMode('simulation');
    applyVisibility();
    drawEdits();
    rebuildSnapTargets();
    requestAnimationFrame(() => fitPlan());
    return true;
  },

  exitPlan() {
    requestRender();
    planActive = false;
    planPoints = [];
    clearGroup(focusGroup);
    clearGroup(draftGroup);
    planControls.enabled = false;
    controls.enabled = true;
    applyVisibility();
    drawEdits();
    requestAnimationFrame(() => { resize(); fitModel(); });
  },

  setPlanLevel(levelKey) {
    requestRender();
    planLevelKey = Number(levelKey);
    planPoints = [];
    clearGroup(focusGroup);
    clearGroup(draftGroup);
    applyVisibility();
    drawEdits();
    rebuildSnapTargets();
    requestAnimationFrame(() => fitPlan());
  },

  setPlanTool(tool) {
    planTool = tool || 'select';
    lastPolygonClosure = null;
    recentPolygonClicks = [];
    planPoints = [];
    clearGroup(draftGroup);
    snapMarker.visible = false;
    rebuildSnapTargets();
  },

  setPlanShape(shape) {
    planShape = shape === 'poly' ? 'poly' : 'rect';
    lastPolygonClosure = null;
    recentPolygonClicks = [];
    planPoints = [];
    clearGroup(draftGroup);
  },

  // Keyboard helpers for drawing.
  planCancel() {
    planPoints = [];
    clearGroup(draftGroup);
  },
  planUndoVertex() {
    planPoints.pop();
    drawDraft(planCursor);
  },
  planFinish() {
    if (planShape === 'poly' && planPoints.length >= 3) finishShape([...planPoints]);
  },
  // Rectangle from the first corner with typed dimensions, towards the cursor.
  planRectBySize(width, depth) {
    if (planShape !== 'rect' || !planPoints.length || !(width > 0) || !(depth > 0)) return false;
    const a = planPoints[0];
    const c = planCursor || [a[0] + 1, a[1] + 1];
    const sx = c[0] >= a[0] ? 1 : -1;
    const sy = c[1] >= a[1] ? 1 : -1;
    finishShape(rectPoints(a, [a[0] + sx * width, a[1] + sy * depth]));
    return true;
  },
  planHasFirstPoint() {
    return planPoints.length > 0;
  },
  // QA helper, analogous to planScreenPoint: inspect pending draft vertices.
  planDraftPoints() {
    return planPoints.map(p => [...p]);
  },

  // UX-02 test hook: wall pieces the drawn passages would still cut in the model on screen.
  pendingPassageCuts() {
    return manualEdits.filter(e => e.kind === 'passage').reduce((n, e) => n + passageCuts(e).length, 0);
  },

  setManualEdits(edits) {
    manualEdits = Array.isArray(edits) ? edits : [];
    if (selectedManualUid && !manualEdits.some(e => e.uid === selectedManualUid)) {
      selectedManualUid = null;
    }
    drawEdits();
    rebuildSnapTargets();
  },

  selectManualEdit(uid, focus = false) {
    const edit = manualEdits.find(e => e.uid === uid);
    if (!edit || !planActive || Number(edit.level_key) !== planLevelKey) return false;
    markManualSelection(edit);
    if (focus) {
      const xs = edit.polygon.map(p => Number(p[0]));
      const ys = edit.polygon.map(p => Number(p[1]));
      const minX = Math.min(...xs), maxX = Math.max(...xs);
      const minY = Math.min(...ys), maxY = Math.max(...ys);
      const radius = Math.max(maxX - minX, maxY - minY, 0.5) / 2;
      this.focusPlanPoint((minX + maxX) / 2, (minY + maxY) / 2, radius, Math.max(5, radius * 4));
    }
    return true;
  },

  isPlan() {
    return planActive;
  },

  // Screen position (client px) of an IFC plan point on the current plan level (QA helper).
  planScreenPoint(x, y) {
    activeCam().updateMatrixWorld();      // frames are drawn on demand: matrices may be one change behind
    const v = new THREE.Vector3(Number(x), levelZ(planLevelKey), -Number(y)).project(activeCam());
    const rect = renderer.domElement.getBoundingClientRect();
    return { x: rect.left + (v.x + 1) / 2 * rect.width, y: rect.top + (1 - v.y) / 2 * rect.height };
  },

  // Centre the plan on (x, y) of the current plan level and ring it (review queue).
  focusPlanPoint(x, y, radius = 1.5, halfHeight = 9) {
    requestRender();
    if (!planActive) return false;
    clearGroup(focusGroup);
    const z = levelZ(planLevelKey) + 0.05;
    const ring = [];
    for (let i = 0; i < 48; i += 1) {
      const a = (i / 48) * Math.PI * 2;
      ring.push([Number(x) + Math.cos(a) * radius, Number(y) + Math.sin(a) * radius]);
    }
    focusGroup.add(outline(ring, z, 0xc8743f, 0.3));
    const cx = Number(x), cz = -Number(y);
    orthoHalfHeight = Math.max(halfHeight, radius * 3);
    orthoCamera.zoom = 1;
    orthoCamera.position.set(cx, levelZ(planLevelKey) + 200, cz);
    planControls.target.set(cx, levelZ(planLevelKey), cz);
    orthoCamera.lookAt(planControls.target);
    resize();
    planControls.update();
    return true;
  },

  clearFocus() {
    clearGroup(focusGroup);
  },

  // Loaded IFC objects whose name, type or GlobalId contains the query (left-panel search).
  searchSource(query, limit = 25) {
    const q = String(query || '').trim().toLowerCase();
    if (q.length < 2) return [];
    const out = [];
    for (const [guid, mesh] of meshes) {
      const item = mesh.userData.item || {};
      const hay = `${guid} ${item.name || ''} ${item.ifc_type || ''}`.toLowerCase();
      if (hay.includes(q)) {
        out.push({ guid, name: item.name || '', type: item.ifc_type || '', storey: item.storey_name || '' });
        if (out.length >= limit) break;
      }
    }
    return out;
  },

  // BIM tree: loaded IFC elements by storey and IFC class, with their current status.
  sourceTree() {
    const tree = new Map();
    for (const [guid, mesh] of meshes) {
      const item = mesh.userData.item || {};
      const storey = item.storey_name || 'Unassigned';
      const type = item.ifc_type || 'IfcElement';
      if (!tree.has(storey)) tree.set(storey, new Map());
      const types = tree.get(storey);
      if (!types.has(type)) types.set(type, []);
      types.get(type).push({ guid, name: item.name || '', status: effectiveStatus(item) });
    }
    return tree;
  },

  hasSource(guid) {
    return !!guid && meshes.has(guid);
  },

  // Jump from a pedestrian-model object to the IFC element it came from.
  showSource(guid) {
    if (!guid || !meshes.has(guid)) return false;
    if (planActive) this.exitPlan();
    this.setMode('source');
    selectGuid(guid, true);
    requestAnimationFrame(() => fitSelection());
    return true;
  },

  fitModel,
  fitSelection,

  isolateSelected() {
    const sem = activeSemanticSelection();
    if (sem) {
      isolatedSemantic = sem;
      applyVisibility();
      fitSelection();
      return true;
    }
    if (!selectedGuid) return false;
    isolatedGuid = selectedGuid;
    applyVisibility();
    fitSelection();
    return true;
  },

  showAll() {
    isolatedGuid = null;
    isolatedSemantic = null;
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

  // Screen position (client px) of a pedestrian-model object's centre - used by
  // browser QA to click a specific object.
  semanticScreenPoint(key) {
    const object = semanticMeshes.find(m => Number(m.userData.semantic?.source?.key) === Number(key));
    if (!object || !object.visible || !semanticGroup.visible) return null;
    const centre = new THREE.Box3().setFromObject(object).getCenter(new THREE.Vector3()).project(activeCam());
    const rect = renderer.domElement.getBoundingClientRect();
    return { x: rect.left + (centre.x + 1) / 2 * rect.width, y: rect.top + (1 - centre.y) / 2 * rect.height };
  },

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
