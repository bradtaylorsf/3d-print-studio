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

renderer.setAnimationLoop((now) => { resize(); buildFx.tick(now); controls.update(); renderer.render(scene, camera); });

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
    entry.mesh.visible = !viewOverride;   // stay hidden while a file view is open
    modelGroup.add(entry.mesh);
  }
}

function frameSubject() {
  // what FIT should frame: the file being viewed, else the floating build
  // card, else the live model. Framing hidden geometry sent the camera to
  // nowhere and read as "FIT is broken".
  if (viewOverride && overrideMesh) return overrideMesh;
  if (buildFx.active && buildFx.group) return buildFx.group;
  return modelGroup;
}
function frameModel(dir) {
  resize();   // the pane may have just split/unsplit — frame for the REAL aspect
  const box = new THREE.Box3().setFromObject(frameSubject());
  if (box.isEmpty()) return;
  const c = box.getCenter(new THREE.Vector3());
  const r = Math.max(box.getSize(new THREE.Vector3()).length() / 2, 20);
  // distance that fits the bounding sphere in BOTH fields of view — a fixed
  // multiplier overflowed wide models whenever the split view narrowed the
  // canvas, which read as "FIT is broken / the model sits off-centre"
  const fovV = THREE.MathUtils.degToRad(camera.fov) / 2;
  const fovH = Math.atan(Math.tan(fovV) * camera.aspect);
  const dist = 1.15 * r / Math.sin(Math.min(fovV, fovH));
  controls.target.copy(c);
  camera.position.copy(c).add(dir.normalize().multiplyScalar(dist));
}
const fitCamera = () => frameModel(new THREE.Vector3(1, -1, 0.8));

// Reloads race: switching projects mid-load once let the OLD project's parts
// finish loading into the cleared scene (and the new project's reload was
// swallowed by a re-entry guard) — the viewer then framed someone else's
// meshes. Generations fix it: the newest call owns the scene, older in-flight
// loops notice and stand down, pulling any straggler mesh back out.
let loadGen = 0;
let loadBusy = false;   // the status poll DEFERS to an in-flight reload rather
                        // than preempting it — a preempted pass restarts from
                        // scratch, and a 1 s poll can starve it forever
async function reloadModel(changed) {
  const gen = ++loadGen;
  loadBusy = true;
  const dot = $('reload-dot');
  dot.className = 'busy';
  toast('loading model…', 0);
  try {
    const manifest = await api(`/api/projects/${project}/manifest`);
    if (gen !== loadGen) return;                    // superseded while fetching
    displayRole = manifest.role;
    const current = new Set(manifest.parts.map((p) => p.file));
    for (const [file, entry] of meshes) {
      if (!current.has(file)) {
        if (entry.mesh) { modelGroup.remove(entry.mesh); entry.mesh.geometry.dispose(); }
        meshes.delete(file);
      }
    }
    for (const part of manifest.parts) {
      if (!meshes.has(part.file)) meshes.set(part.file, { mesh: null, mtime: 0, size: -1, pendingSize: null });
      const entry = meshes.get(part.file);
      if (!changed || changed.has(part.file) || !entry.mesh) await loadPart(part, entry);
      if (gen !== loadGen) {
        // superseded mid-load. If the project switched under us the map was
        // cleared, so this entry is a straggler loadPart just re-added.
        if (entry.mesh && meshes.get(part.file) !== entry) {
          modelGroup.remove(entry.mesh);
          entry.mesh.geometry.dispose();
        }
        return;
      }
    }
    if (firstFit && meshes.size) { fitCamera(); firstFit = false; }
    $('toast').classList.remove('show');
    dot.className = '';
    renderStatsPending(manifest.parts);
    refreshInfo();
    renderFiles();
  } catch (e) {
    if (gen !== loadGen) return;                    // aborted, not failed
    dot.className = 'err';
    toast(`load failed: ${e.message}`);
  } finally {
    if (gen === loadGen) loadBusy = false;          // only the owner clears
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
  const forProject = project;
  try {
    const info = await api(`/api/projects/${project}/info`);
    if (project !== forProject) return;   // switched away while computing
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
        // two consecutive stable polls before fetching (avoid half-written
        // STL) — and never stamp the mtime while a reload is busy, or the
        // change would be recorded as handled without ever loading
        if (!loadBusy && entry.pendingSize === p.size && entry.pendingMtime === p.mtime) {
          entry.mtime = p.mtime; entry.size = p.size;
          entry.pendingSize = null;
          changed.add(p.file);
        } else {
          entry.pendingSize = p.size; entry.pendingMtime = p.mtime;
        }
      }
    }
    if (loadBusy) return;   // defer to the in-flight reload; re-check next tick
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

  } catch {
    $('reload-dot').className = 'err';
  }
}, 1000);

// ---------- the picture library --------------------------------------------
// ONE global pool: every generated or imported image lands in the `library`
// project, and creations are spawned FROM it. One picture -> one model.
const LIB = 'library';
let activeRef = null;           // { file, src } — src is the project serving it
function openRef(file, url, src = LIB) {
  activeRef = { file, src };
  $('ref-viewer').src = url;
  $('ref-pane').hidden = false;
  $('layout').classList.add('split');
  $('refs-strip').querySelectorAll('img').forEach((i) =>
    i.classList.toggle('active', i.title === file));
  updateRefPane();
}
function closeRef() {
  activeRef = null;
  $('ref-pane').hidden = true;
  $('layout').classList.remove('split');
  $('refs-strip').querySelectorAll('img').forEach((i) => i.classList.remove('active'));
}
$('ref-close').onclick = closeRef;
$('ref-make3d').onclick = () => {
  if (!activeRef) return;
  if (refBuilds.some((b) => b.kind === 'toy' && b.has_model && !b.protected)
      && !confirm('Rebuild the toy from this picture? Takes ~5–8 minutes and replaces the current toy.')) return;
  startBuild(activeRef.file, activeRef.src);
};

// The pane is the hub for one picture: its existing builds (a coin AND a toy
// can coexist), redo, and — adult mode only — archiving.
const KIND_EMOJI = { coin: '🪙', toy: '🤖' };
const KIND_WORD = { coin: 'coin', toy: 'toy' };
let refBuilds = [];             // builds of the picture the pane is showing
async function updateRefPane() {
  const kid = document.body.classList.contains('kid');
  const mine = activeRef;
  refBuilds = [];
  $('ref-builds').innerHTML = '';
  $('ref-coin').textContent = '🪙 Make my coin!';
  $('ref-make3d').textContent = '🤖 Make me 3D';
  $('ref-archive').hidden = kid || !mine || mine.src !== LIB;
  if (!mine || mine.src !== LIB) return;
  try {
    const { images } = await api('/api/library');
    if (activeRef !== mine) return;              // pane moved on meanwhile
    refBuilds = images.find((i) => i.file === mine.file)?.builds || [];
  } catch { return; }
  for (const b of refBuilds) {
    const chip = document.createElement('div');
    chip.className = 'ref-build' + (b.project === project ? ' here' : '');
    const open = document.createElement('button');
    open.textContent = `${KIND_EMOJI[b.kind] || '🧊'} see my ${KIND_WORD[b.kind] || 'model'}`;
    open.title = b.project;
    open.onclick = async () => {
      const url = $('ref-viewer').src;
      if (b.project !== project) await refreshProjectList(b.project);
      openRef(mine.file, url, mine.src);         // selectProject closed the pane
      fitCamera();
    };
    chip.appendChild(open);
    if (!kid) {
      const zap = document.createElement('button');
      zap.className = 'zap';
      zap.textContent = '🗂';
      zap.title = `Archive ${b.project} → projects/.archive/`;
      zap.onclick = async () => {
        if (!confirm(`Archive ${b.project}? It moves to projects/.archive/ (recoverable by hand).`)) return;
        const r = await fetch(`/api/projects/${b.project}/archive`, { method: 'POST' });
        const j = await r.json();
        toast(r.ok ? `archived → ${j.archived}` : `archive failed: ${j.error}`, 6000);
        if (r.ok && b.project === project) await refreshProjectList();
        updateRefPane();
        updateKindToggle();
        renderCreations();
        if (!$('kid-home').hidden) renderHome();
      };
      chip.appendChild(zap);
    }
    $('ref-builds').appendChild(chip);
  }
  // hand-built (protected) models are shown but never rebuilt in place —
  // "Redo" only when the studio would actually reuse that project
  if (refBuilds.some((b) => b.kind === 'coin' && b.has_model && !b.protected)) {
    $('ref-coin').textContent = '🪙 Redo my coin';
  }
  if (refBuilds.some((b) => b.kind === 'toy' && b.has_model && !b.protected)) {
    $('ref-make3d').textContent = '🤖 Redo my toy';
  }
}

// ---------- coin/toy toggle: always visible when a picture has both --------
async function updateKindToggle() {
  const holder = $('kind-toggle');
  try {
    const { images } = await api('/api/library');
    const im = images.find((i) => (i.builds || []).some((b) => b.project === project));
    const builds = (im?.builds || []).filter((b) => b.has_model);
    if (builds.length < 2) { holder.hidden = true; holder.innerHTML = ''; return; }
    holder.innerHTML = '';
    for (const b of builds) {
      const btn = document.createElement('button');
      btn.textContent = `${KIND_EMOJI[b.kind] || '🧊'} ${KIND_WORD[b.kind] || 'model'}`;
      btn.className = b.project === project ? 'here' : '';
      btn.title = b.project;
      btn.onclick = () => { if (b.project !== project) selectProject(b.project); };
      holder.appendChild(btn);
    }
    holder.hidden = false;
  } catch { holder.hidden = true; }
}

$('ref-archive').onclick = async () => {
  if (!activeRef || activeRef.src !== LIB) return;
  const f = activeRef.file;
  const kept = refBuilds.length
    ? ` Its ${refBuilds.length} build${refBuilds.length > 1 ? 's' : ''} stay${refBuilds.length > 1 ? '' : 's'}.` : '';
  if (!confirm(`Archive this picture?${kept} It moves to projects/.archive/library_refs/.`)) return;
  const r = await fetch('/api/library/archive',
    { method: 'POST', body: JSON.stringify({ image: f }) });
  const j = await r.json();
  toast(r.ok ? `archived → ${j.archived}` : `archive failed: ${j.error}`, 6000);
  if (r.ok) {
    closeRef();
    renderRefs(true);
    if (!$('kid-home').hidden) renderHome();
  }
};

let libKey = '';
async function renderRefs(force) {
  const { refs } = await api(`/api/projects/${LIB}/refs`);
  const key = refs.map((r) => r.file + r.mtime).join('|');
  if (!force && key === libKey) return;
  libKey = key;
  const strip = $('refs-strip');
  strip.innerHTML = '';
  for (const r of refs.slice().reverse()) {          // newest first
    const img = document.createElement('img');
    img.src = r.url;
    img.title = r.file;
    img.onclick = () =>
      img.classList.contains('active') ? closeRef() : openRef(r.file, r.url, LIB);
    strip.appendChild(img);
  }
  if (!refs.length) strip.innerHTML = '<span class="hint" style="color:var(--dim)">none yet — ✨ make one!</span>';
}
setInterval(() => renderRefs(false), 6000);

// ---------- 3d files browser + view override -------------------------------
let viewOverride = null;      // rel path currently being viewed instead of live
let overrideMesh = null;
let nanoKeyPresent = false;

async function renderFiles() {
  try {
    const j = await api(`/api/projects/${project}/files`);
    nanoKeyPresent = j.nano_key;
    const list = $('files-list');
    if (!j.files.length) { list.innerHTML = '<span class="hint">none yet</span>'; return; }
    list.innerHTML = '';
    let lastKind = null;
    for (const f of j.files) {
      if (f.kind !== lastKind) {
        lastKind = f.kind;
        const g = document.createElement('div');
        g.className = 'file-group';
        g.textContent = { live: 'live', part: 'parts', final: 'final', source: 'source' }[f.kind];
        list.appendChild(g);
      }
      const row = document.createElement('div');
      row.className = 'file-row' + (viewOverride === f.rel ? ' viewing' : '');
      row.innerHTML = `<span class="fname">${f.rel.replace(/^(parts|final|source)\//, '')}</span>` +
        `<span class="fkind">${(f.size / 1024).toFixed(0)}k</span>`;
      row.onclick = () => (viewOverride === f.rel ? backToLive() : viewFile(f.rel));
      list.appendChild(row);
    }
  } catch { /* sidebar only */ }
}

async function viewFile(rel) {
  toast(`loading ${rel}…`, 0);
  try {
    const buf = await fetch(`/api/projects/${project}/file?rel=${encodeURIComponent(rel)}&t=${Date.now()}`)
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.arrayBuffer(); });
    const geom = loader.parse(buf);
    geom.computeVertexNormals();
    // hide the live model, show just this file
    modelGroup.children.forEach((m) => { m.visible = false; });
    if (overrideMesh) { scene.remove(overrideMesh); overrideMesh.geometry.dispose(); }
    overrideMesh = new THREE.Mesh(geom, makeMaterial('#d9a44a'));
    scene.add(overrideMesh);
    viewOverride = rel;
    $('view-banner-label').textContent = `viewing ${rel}`;
    $('view-banner').hidden = false;
    $('toast').classList.remove('show');
    fitCamera();   // frameSubject() sees viewOverride — frames just this file
    renderFiles();
  } catch (e) {
    toast(`could not load ${rel}: ${e.message}`);
  }
}

function backToLive() {
  if (overrideMesh) { scene.remove(overrideMesh); overrideMesh.geometry.dispose(); overrideMesh = null; }
  viewOverride = null;
  modelGroup.children.forEach((m) => { m.visible = true; });
  $('view-banner').hidden = true;
  fitCamera();
  renderFiles();
}
$('view-banner-back').onclick = backToLive;

// ---------- my stuff: one thumbnail per creation, click to visit ----------
async function renderCreations() {
  try {
    const { projects } = await api('/api/projects');
    const strip = $('creations-strip');
    strip.innerHTML = '';
    let shown = 0;
    for (const pr of projects) {
      if (!pr.has_model || pr.name === LIB) continue;
      const { refs } = await api(`/api/projects/${pr.name}/refs`).catch(() => ({ refs: [] }));
      if (!refs?.length) continue;   // no picture, no tile — kids navigate by image
      const holder = document.createElement('div');
      holder.className = 'creation' + (pr.name === project ? ' here' : '');
      holder.title = pr.name;
      const img = document.createElement('img');
      img.src = refs[refs.length - 1].url;
      holder.appendChild(img);
      holder.onclick = () => { if (pr.name !== project) selectProject(pr.name); };
      strip.appendChild(holder);
      shown++;
    }
    $('creations').hidden = shown < 2;   // pointless with one thing
  } catch { /* sidebar only */ }
}
setInterval(renderCreations, 8000);

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
    const target = isMesh ? project : LIB;             // pictures -> the library
    const endpoint = isMesh ? 'source' : 'refs';
    const r = await fetch(`/api/projects/${target}/${endpoint}?name=${encodeURIComponent(file.name)}`,
      { method: 'POST', body: file });
    const j = await r.json();
    toast(r.ok
      ? `saved ${j.path}${j.live_model ? ' — now showing as live model' : ''}`
      : `upload failed: ${j.error}`);
  }
  renderRefs(true);
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

async function doSlice(kid) {
  if (!project) return;
  toast(kid ? 'sending it to the printer… 🖨️' : 'sending to Creality Print…', 0);
  const r = await fetch(`/api/projects/${project}/slice`, { method: 'POST' });
  const j = await r.json();
  if (!r.ok) return toast(kid ? '🙈 that didn’t work — ask a grown-up!' : `slice failed: ${j.error}`, 6000);
  if (kid) {
    $('toast').classList.remove('show');
    $('grownup-overlay').hidden = false;
  } else {
    toast(`opened ${j.opened.length} file${j.opened.length > 1 ? 's' : ''} in ${j.app}${j.role !== 'live' ? ` (from ${j.role}/)` : ''}`, 6000);
  }
}
$('slice-btn').onclick = () => doSlice(false);
$('kid-print-btn').onclick = () => doSlice(true);
$('grownup-ok').onclick = () => { $('grownup-overlay').hidden = true; };

// ---------- painting: pick a color, tap a part -----------------------------
const KID_COLORS = ['#4a90d9', '#e2703a', '#4caf7d', '#b06ab3', '#e8c547', '#d95970',
  '#8d99ae', '#f2f2f4', '#2f2f36'];
let brushColor = null;
for (const c of KID_COLORS) {
  const b = document.createElement('button');
  b.style.background = c;
  b.title = 'pick this color, then tap a part of the model';
  b.onclick = () => {
    const was = b.classList.contains('sel');
    $('swatches').querySelectorAll('button').forEach((x) => x.classList.remove('sel'));
    brushColor = was ? null : c;
    if (!was) b.classList.add('sel');
    if (brushColor && modelGroup.children.length === 1) paintMesh(modelGroup.children[0]);
    else if (brushColor) toast('now tap the part you want to paint!');
  };
  $('swatches').appendChild(b);
}

function fileOfMesh(mesh) {
  for (const [file, e] of meshes) if (e.mesh === mesh) return file;
  return null;
}

async function paintMesh(mesh) {
  mesh.material.color.set(brushColor);
  const file = fileOfMesh(mesh);
  if (!file || viewOverride) return;   // override views are look-only
  await fetch(`/api/projects/${project}/colors`, {
    method: 'POST',
    body: JSON.stringify({ [file.replace(/^parts\//, '')]: brushColor }),
  }).catch(() => {});
}

// click (not drag) on the canvas paints the part under the cursor
const raycaster = new THREE.Raycaster();
let downAt = null;
canvas.addEventListener('pointerdown', (e) => { downAt = [e.clientX, e.clientY]; });
canvas.addEventListener('pointerup', (e) => {
  if (!downAt || !brushColor) return;
  const moved = Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]);
  downAt = null;
  if (moved > 6) return;               // that was an orbit, not a tap
  const r = canvas.getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2(
    ((e.clientX - r.left) / r.width) * 2 - 1,
    -((e.clientY - r.top) / r.height) * 2 + 1), camera);
  const hits = raycaster.intersectObjects(overrideMesh ? [overrideMesh] : modelGroup.children);
  if (hits.length) paintMesh(hits[0].object);
});

// ---------- kid home: full-screen picture grid -----------------------------
// The pictures ARE the interface. Tap one that already has a 3D -> see it
// (the corner toggle switches between its coin and its toy). Tap one that
// doesn't -> the pane offers the choice: coin (~2 s) or toy (the robot).
async function renderHome() {
  try {
    const { images } = await api('/api/library');
    const grid = $('kid-home-grid');
    grid.innerHTML = '';
    const add = document.createElement('div');
    add.className = 'home-tile new-tile';
    add.innerHTML = '✨<span>I want…</span>';
    add.onclick = () => { $('wizard').hidden = false; wizStage('wiz-ask'); $('wiz-input').focus(); };
    grid.appendChild(add);
    for (const im of images.slice().reverse()) {
      const tile = document.createElement('div');
      tile.className = 'home-tile';
      const badges = (im.builds || []).filter((b) => b.has_model)
        .map((b) => KIND_EMOJI[b.kind] || '🧊').join('');
      tile.innerHTML = `<img src="${im.url}" alt="">` +
        (badges ? `<span class="badge3d">${badges}</span>` : '');
      tile.onclick = () => openCreation(im);
      grid.appendChild(tile);
    }
  } catch { /* retry next poll */ }
}

async function openCreation(im) {
  $('kid-home').hidden = true;
  $('kid-back').hidden = !document.body.classList.contains('kid');
  if (im.project && im.project !== project) await refreshProjectList(im.project);
  openRef(im.file, im.url, LIB);   // the pane is the hub: builds, make, redo
  fitCamera();                     // AFTER the split — frame the halved canvas
}

function showHome() {
  closeRef();
  renderHome();
  $('kid-home').hidden = false;
  $('kid-back').hidden = true;
}
$('kid-back').onclick = showHome;
setInterval(() => { if (!$('kid-home').hidden) renderHome(); }, 8000);

// ---------- kid mode -------------------------------------------------------
function setKid(on) {
  document.body.classList.toggle('kid', on);
  localStorage.setItem('kidMode', on ? '1' : '');
  $('gen-btn-label').textContent = on ? 'I want…' : 'generate';
  $('kid-print-btn').hidden = !on;
  if (on) showHome();
  else { $('kid-home').hidden = true; $('kid-back').hidden = true; }
}
$('kid-btn').onclick = () => setKid(!document.body.classList.contains('kid'));
setKid(localStorage.getItem('kidMode') === '1'
  || new URLSearchParams(location.search).get('kid') === '1');

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
  closeRef();
  if (viewOverride) backToLive();
  buildFx.hide();
  for (const [, e] of meshes) { if (e.mesh) { modelGroup.remove(e.mesh); e.mesh.geometry.dispose(); } }
  meshes.clear();
  history.replaceState(null, '', `?project=${encodeURIComponent(name)}`);
  document.title = `${name} — studio`;
  const sel = $('project-select');
  if (sel.value !== name && [...sel.options].some((o) => o.value === name)) sel.value = name;
  renderRefs();
  renderFiles();
  renderCreations();
  updateKindToggle();
  checkBuild();
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

// ---------- ✨ wizard: ask → draw → pick → make me 3D ----------------------
const wizState = { selected: null };
function wizStage(name) {
  for (const s of ['wiz-ask', 'wiz-busy', 'wiz-pick']) $(s).hidden = s !== name;
}
$('gen-btn').onclick = () => {
  if (!project) return;
  $('wizard').hidden = false;
  wizStage('wiz-ask');
  $('wiz-input').focus();
};
$('wizard-close').onclick = () => { $('wizard').hidden = true; };
$('wiz-go').onclick = () => runGenerate();
$('wiz-more').onclick = () => runGenerate();
$('wiz-input').addEventListener('keydown', (e) => { if (e.key === 'Enter') runGenerate(); });

const BUSY_EMOJI = ['🎨', '🖍️', '✏️', '🖌️', '🌈'];
let busyTimer = null;
async function runGenerate() {
  const subject = $('wiz-input').value.trim();
  if (!subject) return;
  const provider = document.querySelector('input[name=prov]:checked')?.value || 'auto';
  wizStage('wiz-busy');
  let i = 0;
  clearInterval(busyTimer);
  busyTimer = setInterval(() => {
    $('wiz-busy-emoji').textContent = BUSY_EMOJI[++i % BUSY_EMOJI.length];
  }, 900);
  try {
    const style = document.body.classList.contains('kid') ? 'sticker' : 'turnaround';
    const r = await fetch(`/api/projects/${LIB}/generate`,
      { method: 'POST', body: JSON.stringify({ subject, provider, style }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.error);
    wizState.selected = null;
    $('wiz-make3d').disabled = true;
    $('wiz-coin').disabled = true;
    const grid = $('wiz-grid');
    grid.innerHTML = '';
    for (const im of j.images) {
      const img = document.createElement('img');
      img.src = im.url;
      img.onclick = () => {
        grid.querySelectorAll('img').forEach((x) => x.classList.remove('sel'));
        img.classList.add('sel');
        wizState.selected = im.file;
        $('wiz-make3d').disabled = false;
        $('wiz-coin').disabled = false;
      };
      grid.appendChild(img);
    }
    wizStage('wiz-pick');
    renderRefs(true);
    if (j.errors?.length) toast(`note: ${j.errors[0]}`, 5000);
  } catch (e) {
    wizStage('wiz-ask');
    const kid = document.body.classList.contains('kid');
    toast(kid ? '🙈 drawing didn’t work — ask a grown-up!' : `generate failed: ${e.message}`, 8000);
  } finally {
    clearInterval(busyTimer);
  }
}

async function makeCoin(imageFile, src = LIB) {
  const kid = document.body.classList.contains('kid');
  const was = activeRef && activeRef.file === imageFile ? { ...activeRef } : null;
  toast(kid ? 'Cutting your coin… 🪙' : 'tracing coin…', 0);
  const r = await fetch(`/api/projects/${src}/coin`,
    { method: 'POST', body: JSON.stringify({ image: imageFile }) });
  const j = await r.json();
  if (!r.ok) {
    return toast(kid ? '🙈 That picture didn’t work — pick another!' : `coin: ${j.error}`, 8000);
  }
  if (j.project !== project) await refreshProjectList(j.project);
  await reloadModel(null);
  buildFx.reveal();
  // selectProject closed the pane — restore it so the builds/toggle stay in reach
  if (was) openRef(was.file, `/api/projects/${was.src}/refs/${was.file}`, was.src);
  updateKindToggle();
  toast(kid ? 'Pick a color, then tap a part to paint it!' : j.report?.split('\n')[0] || 'coin ready', 8000);
}
$('wiz-coin').onclick = () => {
  if (!wizState.selected) return;
  $('wizard').hidden = true;
  $('kid-home').hidden = true;
  $('kid-back').hidden = !document.body.classList.contains('kid');
  makeCoin(wizState.selected);
};
$('ref-coin').onclick = () => { if (activeRef) makeCoin(activeRef.file, activeRef.src); };

$('wiz-make3d').onclick = () => {
  if (!wizState.selected) return;
  $('wizard').hidden = true;
  $('kid-home').hidden = true;
  $('kid-back').hidden = !document.body.classList.contains('kid');
  startBuild(wizState.selected);
};

// ---------- build FX -------------------------------------------------------
// While the robot works: the picture the kid chose floats over the build
// plate (the old model is hidden — it confused people into thinking it was
// the new one). When the build lands: the model pops up out of the plate,
// takes a turntable spin, and gets confetti.
function elasticOut(x) {
  const c4 = (2 * Math.PI) / 3;
  return x <= 0 ? 0 : x >= 1 ? 1 : Math.pow(2, -10 * x) * Math.sin((x * 10 - 0.75) * c4) + 1;
}

const buildFx = {
  active: false, group: null, card: null, sparkles: null,
  revealing: false, revealT0: 0, center: new THREE.Vector3(),

  async show(imageFile) {
    if (this.active) return;
    this.active = true;
    modelGroup.visible = false;
    let tex = null;
    try {
      tex = await new Promise((res, rej) => new THREE.TextureLoader().load(
        `/api/projects/${project}/refs/${imageFile}?t=${Date.now()}`, res, undefined, rej));
    } catch { /* card shows as a plain polaroid */ }
    if (!this.active) { tex?.dispose(); return; }   // cancelled while loading
    const g = new THREE.Group();
    g.position.set(150, 150, 85);
    const w = 100;
    const h = tex?.image ? w * tex.image.height / tex.image.width : w;
    const card = new THREE.Group();
    const backing = new THREE.Mesh(                  // white polaroid frame
      new THREE.PlaneGeometry(w * 1.08, h * 1.08 + 6),
      new THREE.MeshBasicMaterial({ color: 0xffffff, side: THREE.DoubleSide }));
    backing.position.y = -3;
    card.add(backing);
    if (tex) {
      tex.colorSpace = THREE.SRGBColorSpace;
      const img = new THREE.Mesh(
        new THREE.PlaneGeometry(w, h),
        new THREE.MeshBasicMaterial({ map: tex, side: THREE.DoubleSide }));
      img.position.z = 0.5;
      card.add(img);
    }
    g.add(card);
    const pts = [];
    for (let i = 0; i < 46; i++) {
      const a = Math.random() * Math.PI * 2, r = 75 + Math.random() * 22;
      pts.push(r * Math.cos(a), r * Math.sin(a) * 0.4, (Math.random() - 0.5) * 110);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3));
    const sparkles = new THREE.Points(geo, new THREE.PointsMaterial({
      color: 0xe8c547, size: 3.2, sizeAttenuation: true, transparent: true, opacity: 0.9 }));
    g.add(sparkles);
    scene.add(g);
    this.group = g; this.card = card; this.sparkles = sparkles;
  },

  hide() {
    this.active = false;
    if (this.group) {
      scene.remove(this.group);
      this.group.traverse((o) => { o.geometry?.dispose(); o.material?.map?.dispose(); o.material?.dispose?.(); });
      this.group = this.card = this.sparkles = null;
    }
    modelGroup.visible = true;
  },

  reveal() {
    this.hide();
    if (viewOverride) return;               // they're looking at a file — no circus
    fitCamera();
    const box = new THREE.Box3().setFromObject(modelGroup);
    if (!box.isEmpty()) box.getCenter(this.center);
    this.center.z = 0;                      // grow up out of the build plate
    this.revealing = true;
    this.revealT0 = performance.now();
    modelGroup.scale.setScalar(0.001);
    controls.autoRotate = true;
    controls.autoRotateSpeed = 5;
    setTimeout(() => { controls.autoRotate = false; }, 4500);
    confettiBurst();
    revealText(document.body.classList.contains('kid') ? '🎉 It’s here!' : '🎉 built');
  },

  tick(now) {
    const t = now / 1000;
    if (this.card) {
      this.group.position.z = 85 + 6 * Math.sin(t * 1.6);
      this.card.quaternion.copy(camera.quaternion);   // always face the kid
      this.card.rotateZ(0.05 * Math.sin(t * 1.1));    // gentle sway
      this.sparkles.rotation.z = t * 0.45;
    }
    if (this.revealing) {
      const k = (now - this.revealT0) / 950;
      const s = k >= 1 ? 1 : elasticOut(k);
      modelGroup.scale.setScalar(Math.max(s, 0.001));
      modelGroup.position.set(this.center.x * (1 - s), this.center.y * (1 - s), 0);
      if (k >= 1) { this.revealing = false; modelGroup.scale.setScalar(1); modelGroup.position.set(0, 0, 0); }
    }
  },
};
controls.addEventListener('start', () => { controls.autoRotate = false; });  // kid grabs it → their spin wins

function confettiBurst() {
  const holder = document.createElement('div');
  holder.className = 'confetti';
  const colors = ['#4a90d9', '#e2703a', '#4caf7d', '#b06ab3', '#e8c547', '#d95970'];
  for (let i = 0; i < 90; i++) {
    const p = document.createElement('i');
    p.style.left = Math.random() * 100 + '%';
    p.style.background = colors[i % colors.length];
    p.style.animationDelay = Math.random() * 0.7 + 's';
    p.style.animationDuration = 1.6 + Math.random() * 1.5 + 's';
    const s = 6 + Math.random() * 8;
    p.style.width = s + 'px';
    p.style.height = s * 0.45 + 'px';
    holder.appendChild(p);
  }
  $('viewport').appendChild(holder);
  setTimeout(() => holder.remove(), 3800);
}

function revealText(msg) {
  const d = document.createElement('div');
  d.id = 'reveal-text';
  d.textContent = msg;
  $('viewport').appendChild(d);
  setTimeout(() => d.remove(), 2600);
}

// ---------- 🤖 make me 3D: spawn Claude, watch it work ---------------------
async function startBuild(imageFile, src = LIB) {
  const kid = document.body.classList.contains('kid');
  const r = await fetch(`/api/projects/${src}/make3d`,
    { method: 'POST', body: JSON.stringify({ image: imageFile }) });
  const j = await r.json();
  if (!r.ok) {
    return toast(kid ? '🙈 the robot is busy — ask a grown-up!' : `make3d: ${j.error}`, 8000);
  }
  closeRef();
  if (j.project && j.project !== project) {
    await refreshProjectList(j.project);   // the build got its own project
  }
  $('build-banner').hidden = false;
  $('build-banner-text').textContent = kid ? 'The robot is building your 3D…' : 'Claude is building the model…';
  buildFx.show(j.image || imageFile);
}

$('build-cancel').onclick = async () => {
  const r = await fetch(`/api/projects/${project}/make3d/cancel`, { method: 'POST' });
  if (r.ok) { buildFx.hide(); $('build-banner').hidden = true; toast('build stopped'); }
};

let lastBuild = { project: null, state: 'idle' };
async function checkBuild() {
  if (!project) return;
  try {
    const s = await api(`/api/projects/${project}/make3d`);
    if (lastBuild.project !== project) {
      // just arrived here — adopt current state, no false "just finished"
      lastBuild = { project, state: s.state };
      if (s.state !== 'running' && buildFx.active) buildFx.hide();
    }
    const kid = document.body.classList.contains('kid');
    if (s.state === 'running') {
      const m = Math.floor(s.elapsed / 60), sec = String(s.elapsed % 60).padStart(2, '0');
      $('build-banner').hidden = false;
      // once real files land, say so — a long silent build reads as stuck
      const phase = s.wrote_files
        ? (kid ? 'Almost there — making it better… ' : 'Model on disk, refining… ')
        : (kid ? 'The robot is building your 3D… ' : 'Claude is building the model… ');
      $('build-banner-text').textContent = phase + `${m}:${sec}`;
      if (!buildFx.active && s.image) buildFx.show(s.image);  // page opened mid-build
    } else {
      if (lastBuild.state === 'running') {
        $('build-banner').hidden = true;
        if (s.exit === 0) {
          await reloadModel(null);          // make sure the NEW model is what pops up
          buildFx.reveal();
          updateKindToggle();
          toast(kid ? 'Pick a color, then tap a part to paint it!'
                    : 'make3d finished', 9000);
        } else if (s.timed_out && s.wrote_files) {
          // the watchdog stopped it while polishing, but the model landed —
          // that is a finished build, not a failure
          await reloadModel(null);
          buildFx.reveal();
          updateKindToggle();
          toast(kid ? 'Pick a color, then tap a part to paint it!'
                    : 'watchdog stopped a long build, but the model was already exported', 9000);
        } else {
          buildFx.hide();
          if (s.timed_out) {
            toast(kid ? '🙈 The robot took too long — let’s try again!'
                      : 'make3d hit the 18-minute watchdog with nothing exported — try again', 12000);
          } else {
            toast(kid ? '🙈 It got stuck — go ask a grown-up!'
                      : `make3d failed (exit ${s.exit}): …${(s.log_tail || '').slice(-300)}`, 12000);
          }
        }
      } else {
        $('build-banner').hidden = true;
        if (buildFx.active) buildFx.hide(); // stale FX (e.g. server restarted)
      }
    }
    lastBuild = { project, state: s.state };
  } catch { /* poll again */ }
}
setInterval(checkBuild, 3000);

async function refreshProjectList(selectName) {
  const { projects } = await api('/api/projects');
  const sel = $('project-select');
  sel.innerHTML = projects.filter((p) => p.name !== LIB).map((p) =>
    `<option value="${p.name}">${p.name}${p.has_model ? '' : ' (empty)'}</option>`).join('');
  sel.onchange = () => selectProject(sel.value);
  const want = selectName || new URLSearchParams(location.search).get('project');
  const pick = projects.find((p) => p.name === want) || projects.find((p) => p.has_model) || projects[0];
  if (pick) { sel.value = pick.name; await selectProject(pick.name); }
  else $('stats-body').textContent = 'no projects yet';
}
refreshProjectList();

// dev hook: lets tooling (and future debugging) poke the module from the console
window.studio = { buildFx, reloadModel, selectProject, camera, controls, modelGroup,
  fitCamera, THREE, get project() { return project; } };
