import * as THREE from 'three';
import { OrbitControls } from '/static/three/OrbitControls.js';
import { STLLoader } from '/static/three/STLLoader.js';

const $ = (id) => document.getElementById(id);
const api = (p) => fetch(p).then((r) => { if (!r.ok) throw new Error(`${p}: ${r.status}`); return r.json(); });
const isKid = () => document.body.classList.contains('kid');
// for the few innerHTML templates that interpolate config/file-sourced text
// (printer name, parts.json colours, mesh errors)
const esc = (s) => String(s ?? '').replace(/[&<>"']/g,
  (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
// localStorage can throw (private windows, blocked site data) — it only ever
// holds conveniences here, so a failure just means "use the default"
const ls = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* not remembered */ } },
};

// ---------- scene ----------------------------------------------------------
const canvas = $('canvas');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, preserveDrawingBuffer: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.localClippingEnabled = true;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x16181d);

// STL files are Z-up in bed coordinates; keep them that way.
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
camera.up.set(0, 0, 1);              // positioned by homeCamera() once the bed is known

const controls = new OrbitControls(camera, canvas);
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

// Build plate + design envelope: sized from setup.printer (applyBed, below) —
// the K2's 260×260 bed and 255³ envelope until /api/setup answers.
let grid = null;
const envelope = new THREE.Box3Helper(new THREE.Box3(), new THREE.Color(0xd9a44a));
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

// ---------- setup: printer, picture backends, kid wording -----------------
// Everything machine-specific the page shows (bed size, slicer name, who kid
// mode sends the kid to) comes from GET /api/setup, which reads
// studio.config.json. The defaults are the shipped K2 setup, so an older or
// unreachable server still draws a sane bed instead of nothing.
const SETUP_DEFAULTS = {
  options: 4, image_backend: 'auto', resolved_backend: 'claude', problems: [],
  printer: { name: 'Creality K2', bed_mm: [260, 260, 260], envelope_mm: [255, 255, 255], slicer: 'Creality Print' },
  kid: { grown_up: 'a grown-up', ages: '5 to 9' },
  claude: {}, comfyui: {}, nano: {}, ready: {},
};
let setup = mergeSetup({});
let setupAt = 0;

function mergeSetup(j) {
  const D = SETUP_DEFAULTS;
  const dims = (v, fallback) => (Array.isArray(v) && v.length >= 3 && v.slice(0, 3).every((n) => +n > 0)
    ? v.slice(0, 3).map(Number) : fallback.slice());
  const jp = j.printer || {};
  const printer = { ...D.printer, ...jp };
  printer.bed_mm = dims(jp.bed_mm, D.printer.bed_mm);
  // from the answer's own bed, never the K2 default: a 300 mm bed with no
  // envelope_mm must not get the K2's 255³ box
  printer.envelope_mm = dims(jp.envelope_mm, printer.bed_mm.map((v) => Math.max(v - 5, 1)));
  return {
    ...D, ...j, printer,
    kid: { ...D.kid, ...(j.kid || {}) },
    claude: j.claude || {}, comfyui: j.comfyui || {}, nano: j.nano || {}, ready: j.ready || {},
    problems: Array.isArray(j.problems) ? j.problems : [],
  };
}

async function loadSetup() {
  try {
    setup = mergeSetup(await api('/api/setup'));
  } catch { /* no /api/setup (older server, or it's down): keep what we have */ }
  setupAt = Date.now();
  applySetup();
  return setup;
}
// a grown-up who fixed something in a terminal comes back to a fresh banner
addEventListener('focus', () => { if (Date.now() - setupAt > 30000) loadSetup(); });

const grownUp = () => String(setup.kid.grown_up || '').trim() || 'a grown-up';
const optionCount = () => Math.min(8, Math.max(1, Math.round(+setup.options) || 4));
const fmtMm = (v) => String(+(+v).toFixed(1));
function envLabel() {
  const e = setup.printer.envelope_mm.map(fmtMm);
  return e.every((v) => v === e[0]) ? `${e[0]}³` : e.join('×');
}

// Corner-origin grid (meshtools layflat convention: the bed spans 0..X, 0..Y),
// 10 mm squares plus the centre cross GridHelper draws. Hand-built because
// GridHelper is square-only and plenty of beds aren't (250 × 210, …).
function bedGrid(X, Y) {
  const pos = [], col = [];
  const minor = new THREE.Color(0x252a33), major = new THREE.Color(0x3a4150);
  const line = (x1, y1, x2, y2, c) => {
    pos.push(x1, y1, 0, x2, y2, 0);
    col.push(c.r, c.g, c.b, c.r, c.g, c.b);
  };
  const ticks = (n) => {
    const t = [];
    for (let v = 0; v < n - 0.01; v += 10) t.push(v);
    t.push(n);
    return t.filter((v) => Math.abs(v - n / 2) > 0.01);   // the centre line is drawn major
  };
  for (const x of ticks(X)) line(x, 0, x, Y, minor);
  for (const y of ticks(Y)) line(0, y, X, y, minor);
  line(X / 2, 0, X / 2, Y, major);
  line(0, Y / 2, X, Y / 2, major);
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  return new THREE.LineSegments(g, new THREE.LineBasicMaterial({ vertexColors: true, toneMapped: false }));
}

function homeCamera() {
  const [X, Y] = setup.printer.bed_mm, D = Math.max(X, Y);
  controls.target.set(X / 2, Y / 2, 30);
  camera.position.set(X / 2 + 0.67 * D, Y / 2 - 1.67 * D, 0.9 * D);
}

let bedKey = '';
function applyBed() {
  const { bed_mm: bed, envelope_mm: env, name } = setup.printer;
  const key = [...bed, ...env, name].join(',');
  if (key === bedKey) return;
  const first = !bedKey;
  bedKey = key;
  const [X, Y, Z] = bed;
  if (grid) { scene.remove(grid); grid.geometry.dispose(); grid.material.dispose(); }
  grid = bedGrid(X, Y);
  scene.add(grid);
  // the envelope is centred on the bed: half the margin each side, as before
  const mx = Math.max(0, (X - env[0]) / 2), my = Math.max(0, (Y - env[1]) / 2);
  envelope.box.min.set(mx, my, 0);
  envelope.box.max.set(X - mx, Y - my, Math.min(env[2], Z));
  $('envelope-label').textContent = envLabel();
  $('envelope-toggle').parentElement.title = `Show the ${envLabel()} mm design envelope (${name || 'printer'} bed minus margin)`;
  const clip = $('clip-pos'), maxDim = Math.ceil(Math.max(X, Y, Z));
  clip.max = String(maxDim);
  if (+clip.value > maxDim || first) clip.value = String(Math.round(maxDim / 2));
  if (!modelGroup.children.length) homeCamera();   // nothing framed yet — look at THIS bed
  if (project) refreshInfo();                         // the "fits <printer>" row
}

const PROV_NAME = { claude: 'Claude', comfyui: 'ComfyUI', nano: 'Nano Banana' };
let provTouched = false;    // a grown-up's pick this session beats the configured default
function applyProviders() {
  const radios = [...document.querySelectorAll('input[name=prov]')];
  if (!provTouched) {
    const want = { comfy: 'comfyui' }[setup.image_backend] || setup.image_backend || 'auto';
    (radios.find((r) => r.value === want) || radios[0]).checked = true;
  }
  $('prov-auto-label').textContent =
    `auto (${PROV_NAME[setup.resolved_backend] || setup.resolved_backend || 'claude'})`;
  // dim the ones that can't draw yet — still clickable: the server's 503 says how to fix it
  const ready = {
    claude: setup.claude.found !== false && setup.resvg !== false,
    comfyui: setup.comfyui.reachable !== false,
    nano: setup.nano.key !== false,
  };
  for (const r of radios) {
    if (!(r.value in ready)) continue;
    const label = r.closest('label');
    label.classList.toggle('off', !ready[r.value]);
    label.title = ready[r.value] ? '' : 'not set up yet — run scripts/doctor.py for the fix';
  }
}
for (const r of document.querySelectorAll('input[name=prov]')) {
  r.addEventListener('change', () => { provTouched = true; });
}

// grown-up mode only (CSS hides it for kids): the first setup problem + its
// fix, plain text. Dismissing hides it until the set of problems changes.
function renderSetupBanner() {
  const probs = setup.problems;
  const banner = $('setup-banner');
  const key = probs.map((p) => p.what).join('|');
  if (!probs.length || ls.get('setupDismissed') === key) { banner.hidden = true; return; }
  const p = probs[0];
  $('setup-banner-text').textContent = `⚠️ Setup: ${p.what}${p.fix ? ` — ${p.fix}` : ''}`
    + (probs.length > 1 ? ` (+${probs.length - 1} more: run scripts/doctor.py)` : '');
  banner.dataset.key = key;
  banner.hidden = false;
}
$('setup-banner-close').onclick = () => {
  ls.set('setupDismissed', $('setup-banner').dataset.key || '');
  $('setup-banner').hidden = true;
};

function applySetup() {
  applyBed();
  $('slice-btn').title = `Open the displayed model in ${setup.printer.slicer || 'your slicer'}`;
  $('helper-text').textContent = `Go get ${grownUp()} to help you from here.`;
  applyProviders();
  renderSetupBanner();
}
applySetup();                          // defaults now; loadSetup() at the bottom refreshes

// ---------- toast ----------------------------------------------------------
// Text only: toasts carry server- and model-written text (a backend's error,
// the tail of a build's log) and Claude's output can contain markup — parsed
// as HTML it would run in this page. `extra` is an element appended after the
// text (the capture's copy button).
let toastTimer;
function toast(text, ms = 3500, extra = null) {
  const t = $('toast');
  t.textContent = text;
  if (extra) t.appendChild(extra);
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
    parts.map((p) => `<span class="part-chip"><i style="background:${esc(p.color)}"></i>${esc(p.file)}</span>`).join('') +
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
        `<div class="stat-row"><span class="k">${esc(p.file)}</span><span class="badge no">${esc(p.error || 'error')}</span></div>`).join('');
      return;
    }
    const badge = (ok, yes, no) => `<span class="badge ${ok ? 'ok' : 'no'}">${ok ? yes : no}</span>`;
    const rows = [
      ['size', `${c.bbox_mm[0].toFixed(1)} × ${c.bbox_mm[1].toFixed(1)} × ${c.bbox_mm[2].toFixed(1)} mm`],
      ['triangles', c.triangles.toLocaleString()],
      ['watertight', badge(c.watertight, 'yes', 'NO — repair')],
      [`fits ${esc(setup.printer.name || 'bed')}`, badge(c.fits_bed, `≤ ${envLabel()}`, 'TOO BIG')],
    ];
    const vol = info.parts.reduce((s, p) => s + (p.volume_cm3 || 0), 0);
    if (vol) rows.push(['volume', `${vol.toFixed(1)} cm³`]);
    $('stats-body').innerHTML = roleNote() +
      (meshes.size > 1
        ? [...meshes.keys()].map((f, i) => {
            const col = modelGroup.children[i]?.material.color.getStyle() || '#888';
            return `<span class="part-chip"><i style="background:${esc(col)}"></i>${esc(f.replace('parts/', ''))}</span>`;
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
      && !confirm('Rebuild the toy from this picture? Takes ~5–15 minutes and replaces the current toy.')) return;
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
  for (const file of e.dataTransfer.files) {
    const isMesh = /\.(stl|3mf)$/i.test(file.name);
    if (isMesh && !project) { toast('make or pick a project first (+ new)'); continue; }
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
      const copy = document.createElement('button');
      copy.textContent = 'copy path';
      copy.onclick = () => { navigator.clipboard.writeText(j.path); toast('copied'); };
      toast(`📸 ${j.path}`, 8000, copy);
    } else toast(`capture failed: ${j.error}`);
  }, 'image/png');
};

async function doSlice(kid) {
  if (!project) return;
  toast(kid ? 'sending it to the printer… 🖨️' : `sending to ${setup.printer.slicer || 'the slicer'}…`, 0);
  let ok = false, j = {};
  try {
    const r = await fetch(`/api/projects/${project}/slice`, { method: 'POST' });
    ok = r.ok;
    j = await r.json();
  } catch (e) { ok = false; j = { error: j.error || e.message }; }
  if (!ok) {
    const msg = `🙈 That didn’t work — ask ${grownUp()}!`;
    if (kid) say(msg);
    return toast(kid ? msg : `slice failed: ${j.error}`, 6000);
  }
  if (kid) {
    $('toast').classList.remove('show');
    $('helper-overlay').hidden = false;
    say(`Sent to the 3D printer! ${$('helper-text').textContent}`);
  } else {
    const n = (j.opened || []).length;
    const from = j.role && j.role !== 'live' ? ` (from ${j.role === 'slice.json' ? 'slice.json' : `${j.role}/`})` : '';
    toast(`opened ${n} file${n === 1 ? '' : 's'} in ${j.app || setup.printer.slicer}${from}`, 6000);
  }
}
$('slice-btn').onclick = () => doSlice(false);
$('kid-print-btn').onclick = () => doSlice(true);
$('helper-ok').onclick = () => { $('helper-overlay').hidden = true; };

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
    add.onclick = openWizard;
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
  ls.set('kidMode', on ? '1' : '');
  $('gen-btn-label').textContent = on ? 'I want…' : 'generate';
  $('kid-print-btn').hidden = !on;
  renderVoiceBtn();
  if (on) showHome();
  else { $('kid-home').hidden = true; $('kid-back').hidden = true; stopSpeaking(); }
}
$('kid-btn').onclick = () => setKid(!isKid());

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
function openWizard() {
  $('wizard').hidden = false;
  wizStage('wiz-ask');
  hideWizMsg();
  $('wiz-input').focus();
  loadSetup();     // fresh backend + readiness every time the wizard opens
}
function closeWizard() {
  $('wizard').hidden = true;
  genRun++;        // abandon an in-flight draw — its pictures still land in the library
  clearInterval(busyTimer);
  stopListening(true);
  stopSpeaking();
}
// the ask stage's message line: wraps (a toast truncates), and kid mode reads it out
function showWizMsg(text) {
  $('wiz-msg').textContent = text;
  $('wiz-msg').hidden = false;
  say(text);
}
function hideWizMsg() { $('wiz-msg').hidden = true; }

$('gen-btn').onclick = openWizard;
$('wizard-close').onclick = closeWizard;
addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('wizard').hidden) closeWizard(); });
$('wiz-go').onclick = () => { primeSpeech(); runGenerate(); };
$('wiz-more').onclick = () => { primeSpeech(); runGenerate(); };
$('wiz-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.isComposing && !e.repeat) { primeSpeech(); runGenerate(); }
});

function busyText(provider, n) {
  if (isKid()) return 'Drawing your pictures… 🎨';
  const b = provider === 'auto' ? setup.resolved_backend : provider === 'comfy' ? 'comfyui' : provider;
  const pics = `${n} picture${n === 1 ? '' : 's'}`;
  return { claude: `Claude is drawing ${pics}…`, comfyui: `Painting ${pics}…`,
    nano: `Nano Banana is drawing ${pics}…` }[b] || `Drawing ${pics}…`;
}

const BUSY_EMOJI = ['🎨', '🖍️', '✏️', '🖌️', '🌈'];
let busyTimer = null;
let genRun = 0;    // the newest draw owns the wizard; older answers only refresh the library
async function runGenerate() {
  // one draw at a time: a held Enter key (auto-repeat reaches the input before
  // it loses focus) or a double tap would start another `count` paid drawings
  // per press, and only the last answer would ever be shown
  if (!$('wiz-busy').hidden) return;
  const subject = $('wiz-input').value.trim();
  if (!subject) { $('wiz-input').focus(); return; }
  stopListening(true);
  stopSpeaking();
  hideWizMsg();
  const kid = isKid();
  // kids always get the configured backend; the radios are a grown-up tool
  const provider = kid ? 'auto' : (document.querySelector('input[name=prov]:checked')?.value || 'auto');
  const count = optionCount();
  const run = ++genRun;
  wizStage('wiz-busy');
  $('wiz-busy-text').textContent = busyText(provider, count);
  // 20–60 s is normal (Claude draws each option in its own headless call):
  // a ticking clock reads as working, a frozen spinner reads as stuck
  const t0 = Date.now();
  const tick = () => {
    const sec = Math.round((Date.now() - t0) / 1000);
    $('wiz-busy-time').textContent = kid ? `${sec} s` : `${sec} s · usually 20–60 s`;
  };
  let i = 0;
  tick();
  clearInterval(busyTimer);
  busyTimer = setInterval(() => {
    $('wiz-busy-emoji').textContent = BUSY_EMOJI[++i % BUSY_EMOJI.length];
    tick();
  }, 1000);
  try {
    const style = kid ? 'sticker' : 'turnaround';   // stickers trace best into coins
    const r = await fetch(`/api/projects/${LIB}/generate`,
      { method: 'POST', body: JSON.stringify({ subject, provider, style, count }) });
    const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
    if (run !== genRun) { renderRefs(true); return; }   // closed or re-asked meanwhile
    if (!r.ok || !j.images?.length) {
      const err = new Error(j.error || `HTTP ${r.status}`);
      err.setup = !!j.setup;
      err.fix = j.fix;
      throw err;
    }
    showOptions(j, kid);
    renderRefs(true);
  } catch (e) {
    if (run !== genRun) return;
    wizStage('wiz-ask');
    if (e.setup) {
      // 503 {setup: true}: the backend isn't installed/running — no point retrying
      loadSetup();
      showWizMsg(kid ? `🙈 The picture machine isn’t ready — ask ${grownUp()}!`
                     : `${e.message}${e.fix ? `\nfix: ${e.fix}` : ''}`);
    } else {
      showWizMsg(kid ? `🙈 Drawing didn’t work — ask ${grownUp()}!` : `generate failed: ${e.message}`);
    }
  } finally {
    if (run === genRun) clearInterval(busyTimer);
  }
}

// the 2×2 pick grid: big tiles, each with the backend's title when it gave one
function showOptions(j, kid) {
  wizState.selected = null;
  $('wiz-make3d').disabled = true;
  $('wiz-coin').disabled = true;
  const grid = $('wiz-grid');
  grid.innerHTML = '';
  grid.classList.toggle('single', j.images.length === 1);
  j.images.forEach((im, n) => {
    const opt = document.createElement('button');
    opt.type = 'button';
    opt.className = 'wiz-opt';
    const img = document.createElement('img');
    img.src = im.url;
    img.alt = im.title || `picture ${n + 1}`;
    opt.appendChild(img);
    if (im.title) {
      const t = document.createElement('span');
      t.className = 'wiz-title';
      t.textContent = im.title;     // model-written text: never innerHTML
      opt.appendChild(t);
    }
    opt.onclick = () => {
      grid.querySelectorAll('.wiz-opt').forEach((x) => x.classList.remove('sel'));
      opt.classList.add('sel');
      wizState.selected = im.file;
      $('wiz-make3d').disabled = false;
      $('wiz-coin').disabled = false;
      if (im.title) say(im.title);
    };
    grid.appendChild(opt);
  });
  const n = j.images.length;
  const reply = j.reply || `I drew ${n} picture${n === 1 ? '' : 's'}! Which one do you like best?`;
  $('wiz-pick-title').textContent = kid ? reply : 'Pick your favorite!';
  wizStage('wiz-pick');
  say(reply);
  if (!kid && j.errors?.length) toast(`note: ${j.errors[0]}`, 5000);
}

// ---------- voice: talk to it, and (kid mode) it talks back ---------------
// Both directions use the BROWSER's own engines: the page never records or
// uploads audio itself. Where an engine is missing (Firefox has no
// SpeechRecognition) its button just isn't shown and typing still works.
const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
const canSpeak = 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
let voiceOn = ls.get('kidVoice') !== '0';    // read-aloud: default on
let sayTimer = null;

function renderVoiceBtn() {
  const b = $('voice-btn');
  b.hidden = !canSpeak;
  b.textContent = voiceOn ? '🔊' : '🔇';
  b.title = voiceOn ? 'Reading things out loud — tap for quiet' : 'Quiet — tap to read things out loud';
}
$('voice-btn').onclick = () => {
  voiceOn = !voiceOn;
  ls.set('kidVoice', voiceOn ? '1' : '0');
  renderVoiceBtn();
  if (voiceOn) say('OK! I’ll read things out loud.');
  else stopSpeaking();
};

function stopSpeaking() {
  clearTimeout(sayTimer);
  if (canSpeak) speechSynthesis.cancel();
}
function say(text) {
  if (!canSpeak || !voiceOn || !text || !isKid()) return;
  // emoji get read out by name ("see-no-evil monkey") — drop them
  const clean = String(text).replace(/[\p{Extended_Pictographic}\u{FE0F}\u{200D}]/gu, '')
    .replace(/\s+/g, ' ').trim();
  if (!clean) return;
  stopSpeaking();              // the newest thing said wins
  // Chrome can drop an utterance queued in the same tick as cancel()
  sayTimer = setTimeout(() => {
    const u = new SpeechSynthesisUtterance(clean);
    u.lang = navigator.language || 'en-US';
    u.rate = 0.95;
    u.pitch = 1.1;
    speechSynthesis.speak(u);
  }, 60);
}
// Safari only lets a page speak after it has spoken inside a tap once
let speechPrimed = false;
function primeSpeech() {
  if (speechPrimed || !canSpeak) return;
  speechPrimed = true;
  try { speechSynthesis.speak(new SpeechSynthesisUtterance('')); } catch { /* no voice */ }
}

let rec = null;     // the live SpeechRecognition, if listening
function micUi(on) {
  $('wiz-mic').classList.toggle('listening', on);
  $('wiz-mic-label').textContent = on ? 'Listening…' : 'Tell me!';
  $('wiz-mic').title = on ? 'Tap when you’re done talking' : 'Say what you want to make';
}
function micError(code) {
  if (code === 'aborted') return;
  const kid = isKid(), gu = grownUp();
  const blocked = kid ? `🙈 I can’t hear you — ask ${gu} to turn on the microphone!`
    : 'microphone blocked — allow it for this page in the browser’s site settings';
  const msg = {
    'no-speech': kid ? 'I didn’t hear anything — tap 🎤 and try again!' : 'no speech heard — try again',
    'not-allowed': blocked,
    'service-not-allowed': blocked,
    'audio-capture': kid ? `🙈 I can’t find a microphone — ask ${gu}!` : 'no microphone found',
    network: kid ? '🙈 Talking isn’t working right now — type it instead!'
      : 'this browser’s speech recognition needs a network connection — type instead',
  }[code];
  showWizMsg(msg || (kid ? '🙈 Talking didn’t work — type it instead!' : `voice input failed: ${code}`));
}
function startListening() {
  stopSpeaking();              // don't let it hear its own voice
  hideWizMsg();
  let r;
  try { r = new SpeechRec(); } catch { micError('unavailable'); return; }
  r.lang = navigator.language || 'en-US';
  r.interimResults = true;     // words appear as they're said
  r.continuous = false;        // one request per tap
  r.maxAlternatives = 1;
  let finalText = '', heard = '', failed = false;
  r.onresult = (e) => {
    let interim = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const res = e.results[i];
      if (res.isFinal) finalText += res[0].transcript;
      else interim += res[0].transcript;
    }
    heard = `${finalText} ${interim}`.replace(/\s+/g, ' ').trim();
    if (heard) $('wiz-input').value = heard;
  };
  r.onerror = (e) => { failed = true; micError(e.error); };
  r.onend = () => {
    if (rec !== r) return;     // aborted or replaced
    rec = null;
    micUi(false);
    // done talking -> draw it. (Safari can end on a stop() without a final
    // result; the words already in the box are what the kid said.)
    if (heard && !failed && !$('wizard').hidden && !$('wiz-ask').hidden) runGenerate();
  };
  rec = r;
  try { r.start(); } catch { rec = null; micError('unavailable'); return; }
  micUi(true);
}
function stopListening(abort) {
  const r = rec;
  if (!r) return;
  if (abort) { rec = null; micUi(false); r.abort(); } else r.stop();   // stop() keeps what was said
}
if (SpeechRec) {
  $('wiz-mic').hidden = false;
  $('wiz-mic').onclick = () => { primeSpeech(); if (rec) stopListening(false); else startListening(); };
}

setKid(ls.get('kidMode') === '1' || new URLSearchParams(location.search).get('kid') === '1');

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
  active: false, group: null, card: null, sparkles: null, baseZ: 85,
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
    // float over the middle of THIS bed, scaled to its size
    const [X, Y] = setup.printer.bed_mm;
    const k = THREE.MathUtils.clamp(Math.max(X, Y) / 300, 0.6, 1.2);
    this.baseZ = 85 * k;
    g.position.set(X / 2, Y / 2, this.baseZ);
    g.scale.setScalar(k);
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
    say('It’s here! Pick a color, then tap a part to paint it!');   // kid mode only
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
      this.group.position.z = this.baseZ + 6 * Math.sin(t * 1.6);
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
    const msg = `🙈 The robot is busy — ask ${grownUp()}!`;
    if (kid) say(msg);
    return toast(kid ? msg : `make3d: ${j.error}`, 8000);
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
          markHasModel(project);
          toast(kid ? 'Pick a color, then tap a part to paint it!'
                    : 'make3d finished', 9000);
        } else if (s.timed_out && s.wrote_files) {
          // the watchdog stopped it while polishing, but the model landed —
          // that is a finished build, not a failure
          await reloadModel(null);
          buildFx.reveal();
          updateKindToggle();
          markHasModel(project);
          toast(kid ? 'Pick a color, then tap a part to paint it!'
                    : 'watchdog stopped a long build, but the model was already exported', 9000);
        } else {
          buildFx.hide();
          if (s.timed_out) {
            if (kid) say('The robot took too long — let’s try again!');
            toast(kid ? '🙈 The robot took too long — let’s try again!'
                      : `make3d hit the ${s.timeout_min || '?'}-minute watchdog (claude.build_timeout_min) with nothing exported — try again`, 12000);
          } else {
            if (kid) say(`It got stuck — go ask ${grownUp()}!`);
            toast(kid ? `🙈 It got stuck — go ask ${grownUp()}!`
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

// a build that just landed: drop the dropdown's stale " (empty)" without a full reload
function markHasModel(name) {
  const opt = [...$('project-select').options].find((o) => o.value === name);
  if (opt) opt.textContent = name;
}

async function refreshProjectList(selectName) {
  const { projects } = await api('/api/projects');
  const sel = $('project-select');
  sel.innerHTML = projects.filter((p) => p.name !== LIB).map((p) =>
    `<option value="${esc(p.name)}">${esc(p.name)}${p.has_model ? '' : ' (empty)'}</option>`).join('');
  sel.onchange = () => selectProject(sel.value);
  const want = selectName || new URLSearchParams(location.search).get('project');
  const pick = projects.find((p) => p.name === want) || projects.find((p) => p.has_model) || projects[0];
  if (pick) { sel.value = pick.name; await selectProject(pick.name); }
  else $('stats-body').textContent = 'no projects yet';
}
loadSetup();            // parallel: the page works on the defaults until it answers
refreshProjectList();

// dev hook: lets tooling (and future debugging) poke the module from the console
window.studio = { buildFx, reloadModel, selectProject, camera, controls, modelGroup,
  fitCamera, loadSetup, THREE, get project() { return project; }, get setup() { return setup; } };
