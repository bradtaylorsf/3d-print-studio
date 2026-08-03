import * as THREE from 'three';
import { OrbitControls } from '/static/three/OrbitControls.js';
import { STLLoader } from '/static/three/STLLoader.js';

const $ = (id) => document.getElementById(id);
const api = (p) => fetch(p).then((r) => { if (!r.ok) throw new Error(`${p}: ${r.status}`); return r.json(); });

// ---------- scene ----------------------------------------------------------
const canvas = $('canvas');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.localClippingEnabled = true;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x16181d);

// STL files are Z-up in bed coordinates; keep them that way.
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
camera.up.set(0, 0, 1);
camera.position.set(350, -350, 300);

const controls = new OrbitControls(camera, canvas);
controls.target.set(150, 150, 30);
controls.enableDamping = true;
controls.listenToKeyEvents(window);   // arrow keys pan
controls.keyPanSpeed = 20;

// Shift-drag pans (right-drag is awkward on trackpads).
addEventListener('keydown', (e) => { if (e.key === 'Shift') controls.mouseButtons.LEFT = THREE.MOUSE.PAN; });
addEventListener('keyup', (e) => { if (e.key === 'Shift') controls.mouseButtons.LEFT = THREE.MOUSE.ROTATE; });

scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.1));
for (const [x, y, z, i] of [[300, -200, 400, 1.2], [-200, 300, 250, 0.5]]) {
  const d = new THREE.DirectionalLight(0xffffff, i);
  d.position.set(x, y, z);
  scene.add(d);
}

// Build plate: K2 bed is 300x300 in XY, origin at corner (meshtools layflat convention).
const grid = new THREE.GridHelper(300, 30, 0x3a4150, 0x252a33);
grid.rotation.x = Math.PI / 2;
grid.position.set(150, 150, 0);
scene.add(grid);

const envelope = new THREE.Box3Helper(
  new THREE.Box3(new THREE.Vector3(2.5, 2.5, 0), new THREE.Vector3(297.5, 297.5, 295)),
  new THREE.Color(0xd9a44a));
envelope.visible = false;
scene.add(envelope);

const modelGroup = new THREE.Group();
scene.add(modelGroup);

function resize() {
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== w * devicePixelRatio || canvas.height !== h * devicePixelRatio) {
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
}
new ResizeObserver(resize).observe(canvas);

renderer.setAnimationLoop(() => { resize(); controls.update(); renderer.render(scene, camera); });

// ---------- state ----------------------------------------------------------
let project = null;
const meshes = new Map();      // part file -> { mesh, mtime, size, pendingSize }
let firstFit = true;
let refsKey = '';
const loader = new STLLoader();
const clipPlane = new THREE.Plane(new THREE.Vector3(-1, 0, 0), 300);
let clipping = false;

// ---------- toast ----------------------------------------------------------
let toastTimer;
function toast(html, ms = 3500) {
  const t = $('toast');
  t.innerHTML = html;
  t.classList.add('show');
  clearTimeout(toastTimer);
  if (ms) toastTimer = setTimeout(() => t.classList.remove('show'), ms);
}

// ---------- model loading --------------------------------------------------
function makeMaterial(color) {
  return new THREE.MeshStandardMaterial({
    color, metalness: 0.05, roughness: 0.65,
    clippingPlanes: clipping ? [clipPlane] : [], side: THREE.DoubleSide,
  });
}

async function loadPart(part, entry) {
  const buf = await fetch(part.url + '?t=' + Date.now()).then((r) => {
    if (!r.ok) throw new Error(`${part.file}: HTTP ${r.status}`);
    return r.arrayBuffer();
  });
  // Let the toast paint before the parse freeze. setTimeout, not rAF — rAF never
  // fires in a hidden tab and would hang the reload until the tab is visible again.
  await new Promise((res) => setTimeout(res, 16));
  const geom = loader.parse(buf);
  geom.computeVertexNormals();
  if (entry.mesh) {
    entry.mesh.geometry.dispose();
    entry.mesh.geometry = geom;
  } else {
    entry.mesh = new THREE.Mesh(geom, makeMaterial(part.color));
    modelGroup.add(entry.mesh);
  }
}

function frameModel(dir) {
  const box = new THREE.Box3().setFromObject(modelGroup);
  if (box.isEmpty()) return;
  const c = box.getCenter(new THREE.Vector3());
  const r = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 20);
  controls.target.copy(c);
  camera.position.copy(c).add(dir.normalize().multiplyScalar(r * 2.4));
}
const fitCamera = () => frameModel(new THREE.Vector3(1, -1, 0.8));

let loading = false;
async function reloadModel(changed) {
  if (loading) return;
  loading = true;
  const dot = $('reload-dot');
  dot.className = 'busy';
  toast('loading model…', 0);
  try {
    const manifest = await api(`/api/projects/${project}/manifest`);
    displayRole = manifest.role;
    const current = new Set(manifest.parts.map((p) => p.file));
    for (const [file, entry] of meshes) {
      if (!current.has(file)) {
        modelGroup.remove(entry.mesh);
        entry.mesh.geometry.dispose();
        meshes.delete(file);
      }
    }
    for (const part of manifest.parts) {
      if (!meshes.has(part.file)) meshes.set(part.file, { mesh: null, mtime: 0, size: -1, pendingSize: null });
      const entry = meshes.get(part.file);
      if (!changed || changed.has(part.file) || !entry.mesh) await loadPart(part, entry);
    }
    if (firstFit && meshes.size) { fitCamera(); firstFit = false; }
    $('toast').classList.remove('show');
    dot.className = '';
    renderStatsPending(manifest.parts);
    refreshInfo();
  } catch (e) {
    dot.className = 'err';
    toast(`load failed: ${e.message}`);
  } finally {
    loading = false;
  }
}

// ---------- stats ----------------------------------------------------------
let displayRole = 'live';
function roleNote() {
  if (displayRole === 'live' || displayRole === 'none') return '';
  return `<div class="stat-row"><span class="k" style="color:var(--dim)">showing ${displayRole}/ — no live model.stl yet</span></div>`;
}

function renderStatsPending(parts) {
  $('stats-body').innerHTML =
    parts.map((p) => `<span class="part-chip"><i style="background:${p.color}"></i>${p.file}</span>`).join('') +
    roleNote() +
    '<div class="stat-row"><span class="k">stats</span><span>computing…</span></div>';
}

async function refreshInfo() {
  try {
    const info = await api(`/api/projects/${project}/info`);
    const c = info.combined;
    if (!c || !Object.keys(c).length) {
      $('stats-body').innerHTML = info.parts.map((p) =>
        `<div class="stat-row"><span class="k">${p.file}</span><span class="badge no">${p.error || 'error'}</span></div>`).join('');
      return;
    }
    const badge = (ok, yes, no) => `<span class="badge ${ok ? 'ok' : 'no'}">${ok ? yes : no}</span>`;
    const rows = [
      ['size', `${c.bbox_mm[0].toFixed(1)} × ${c.bbox_mm[1].toFixed(1)} × ${c.bbox_mm[2].toFixed(1)} mm`],
      ['triangles', c.triangles.toLocaleString()],
      ['watertight', badge(c.watertight, 'yes', 'NO — repair')],
      ['fits K2', badge(c.fits_295, '≤ 295³', 'TOO BIG')],
    ];
    const vol = info.parts.reduce((s, p) => s + (p.volume_cm3 || 0), 0);
    if (vol) rows.push(['volume', `${vol.toFixed(1)} cm³`]);
    $('stats-body').innerHTML = roleNote() +
      (meshes.size > 1
        ? [...meshes.keys()].map((f, i) => {
            const col = modelGroup.children[i]?.material.color.getStyle() || '#888';
            return `<span class="part-chip"><i style="background:${col}"></i>${f.replace('parts/', '')}</span>`;
          }).join('')
        : '') +
      rows.map(([k, v]) => `<div class="stat-row"><span class="k">${k}</span><span>${v}</span></div>`).join('');
  } catch { /* keep old stats */ }
}

// ---------- polling / hot reload ------------------------------------------
setInterval(async () => {
  if (!project) return;
  try {
    const st = await api(`/api/projects/${project}/status`);
    $('reload-dot').className = $('reload-dot').className === 'busy' ? 'busy' : '';

    const changed = new Set();
    let structure = st.parts.length !== meshes.size;
    for (const p of st.parts) {
      const entry = meshes.get(p.file);
      if (!entry) { structure = true; continue; }
      if (p.mtime !== entry.mtime) {
        // two consecutive stable polls before fetching (avoid half-written STL)
        if (entry.pendingSize === p.size && entry.pendingMtime === p.mtime) {
          entry.mtime = p.mtime; entry.size = p.size;
          entry.pendingSize = null;
          changed.add(p.file);
        } else {
          entry.pendingSize = p.size; entry.pendingMtime = p.mtime;
        }
      }
    }
    if (structure) {
      // parts appeared/disappeared: seed entries so next stable poll reloads
      await reloadModel(null);
      const st2 = await api(`/api/projects/${project}/status`);
      for (const p of st2.parts) {
        const e = meshes.get(p.file);
        if (e) { e.mtime = p.mtime; e.size = p.size; }
      }
    } else if (changed.size) {
      await reloadModel(changed);
    }

    const rk = st.refs.map((r) => r.file + r.mtime).join('|');
    if (rk !== refsKey) { refsKey = rk; renderRefs(); }
  } catch {
    $('reload-dot').className = 'err';
  }
}, 1000);

// ---------- refs -----------------------------------------------------------
async function renderRefs() {
  const { refs } = await api(`/api/projects/${project}/refs`);
  const strip = $('refs-strip');
  strip.innerHTML = '';
  for (const r of refs) {
    const img = document.createElement('img');
    img.src = r.url;
    img.title = r.file;
    img.onclick = () => {
      const viewer = $('ref-viewer');
      const active = img.classList.contains('active');
      strip.querySelectorAll('img').forEach((i) => i.classList.remove('active'));
      if (active) {
        viewer.hidden = true;
        $('layout').classList.remove('split');
      } else {
        img.classList.add('active');
        viewer.src = r.url;
        viewer.hidden = false;
        $('layout').classList.add('split');
      }
    };
    strip.appendChild(img);
  }
  if (!refs.length) strip.innerHTML = '<span class="hint" style="color:var(--dim)">none yet</span>';
}

// drag & drop upload
let dragDepth = 0;
addEventListener('dragenter', (e) => { e.preventDefault(); if (++dragDepth) document.body.classList.add('dragging'); });
addEventListener('dragleave', () => { if (!--dragDepth) document.body.classList.remove('dragging'); });
addEventListener('dragover', (e) => e.preventDefault());
addEventListener('drop', async (e) => {
  e.preventDefault();
  dragDepth = 0;
  document.body.classList.remove('dragging');
  if (!project) return;
  for (const file of e.dataTransfer.files) {
    const isMesh = /\.(stl|3mf)$/i.test(file.name);
    const endpoint = isMesh ? 'source' : 'refs';
    const r = await fetch(`/api/projects/${project}/${endpoint}?name=${encodeURIComponent(file.name)}`,
      { method: 'POST', body: file });
    const j = await r.json();
    toast(r.ok
      ? `saved ${j.path}${j.live_model ? ' — now showing as live model' : ''}`
      : `upload failed: ${j.error}`);
  }
});

// ---------- new project / URL import --------------------------------------
$('new-project-btn').onclick = async () => {
  const name = prompt('New project name (lowercase, underscores):');
  if (!name) return;
  const r = await fetch('/api/projects', { method: 'POST', body: JSON.stringify({ name }) });
  const j = await r.json();
  if (!r.ok) return toast(`create failed: ${j.error}`);
  toast(j.created ? `created projects/${j.name}/ — drop images or STLs to begin`
                  : `projects/${j.name}/ already existed — switched to it`);
  await refreshProjectList(j.name);
};

$('url-btn').onclick = async () => {
  if (!project) return;
  const u = prompt('Public URL of an image or STL/3MF to import:');
  if (!u) return;
  toast('downloading…', 0);
  const r = await fetch(`/api/projects/${project}/import-url`,
    { method: 'POST', body: JSON.stringify({ url: u }) });
  const j = await r.json();
  toast(r.ok
    ? `saved ${j.path} (${(j.bytes / 1024).toFixed(0)} KB)${j.live_model ? ' — now showing as live model' : ''}`
    : j.error, 6000);
};

// ---------- capture --------------------------------------------------------
$('capture-btn').onclick = () => {
  renderer.render(scene, camera);
  canvas.toBlob(async (blob) => {
    const r = await fetch(`/api/projects/${project}/capture`, { method: 'POST', body: blob });
    const j = await r.json();
    if (r.ok) {
      toast(`📸 ${j.path} <button id="copy-path">copy path</button>`, 8000);
      $('copy-path').onclick = () => { navigator.clipboard.writeText(j.path); toast('copied'); };
    } else toast(`capture failed: ${j.error}`);
  }, 'image/png');
};

$('slice-btn').onclick = async () => {
  if (!project) return;
  toast('sending to Creality Print…', 0);
  const r = await fetch(`/api/projects/${project}/slice`, { method: 'POST' });
  const j = await r.json();
  toast(r.ok
    ? `opened ${j.opened.length} file${j.opened.length > 1 ? 's' : ''} in ${j.app}${j.role !== 'live' ? ` (from ${j.role}/)` : ''}`
    : `slice failed: ${j.error}`, 6000);
};

// ---------- preset views ---------------------------------------------------
const VIEW_DIRS = {
  front: [0, -1, 0], back: [0, 1, 0], left: [-1, 0, 0], right: [1, 0, 0],
  top: [0, 0.0001, 1], iso: [1, -1, 0.8],
};
$('fit-btn').onclick = fitCamera;
canvas.addEventListener('dblclick', fitCamera);
$('view-buttons').addEventListener('click', (e) => {
  const v = e.target.dataset?.view;
  if (!v) return;
  frameModel(new THREE.Vector3(...VIEW_DIRS[v]));
});

// ---------- clip plane & envelope -----------------------------------------
$('envelope-toggle').onchange = (e) => { envelope.visible = e.target.checked; };
const AXES = { x: new THREE.Vector3(-1, 0, 0), y: new THREE.Vector3(0, -1, 0), z: new THREE.Vector3(0, 0, -1) };
function applyClip() {
  const axis = $('clip-axis').value;
  clipping = !!axis;
  $('clip-pos').disabled = !clipping;
  if (clipping) {
    clipPlane.normal.copy(AXES[axis]);
    clipPlane.constant = Number($('clip-pos').value);
  }
  modelGroup.children.forEach((m) => { m.material.clippingPlanes = clipping ? [clipPlane] : []; });
}
$('clip-axis').onchange = applyClip;
$('clip-pos').oninput = applyClip;

// ---------- project selection ---------------------------------------------
async function selectProject(name) {
  project = name;
  firstFit = true;
  refsKey = '';
  for (const [, e] of meshes) { if (e.mesh) { modelGroup.remove(e.mesh); e.mesh.geometry.dispose(); } }
  meshes.clear();
  history.replaceState(null, '', `?project=${encodeURIComponent(name)}`);
  document.title = `${name} — studio`;
  renderRefs();
  const st = await api(`/api/projects/${project}/status`);
  if (st.parts.length) {
    await reloadModel(null);
    for (const p of st.parts) {
      const e = meshes.get(p.file);
      if (e) { e.mtime = p.mtime; e.size = p.size; }
    }
  } else {
    $('stats-body').textContent = 'empty project — drop an image or STL, use 🔗 url, or ask Claude for a first version';
  }
}

async function refreshProjectList(selectName) {
  const { projects } = await api('/api/projects');
  const sel = $('project-select');
  sel.innerHTML = projects.map((p) =>
    `<option value="${p.name}">${p.name}${p.has_model ? '' : ' (empty)'}</option>`).join('');
  sel.onchange = () => selectProject(sel.value);
  const want = selectName || new URLSearchParams(location.search).get('project');
  const pick = projects.find((p) => p.name === want) || projects.find((p) => p.has_model) || projects[0];
  if (pick) { sel.value = pick.name; await selectProject(pick.name); }
  else $('stats-body').textContent = 'no projects yet';
}
refreshProjectList();
