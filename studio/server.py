#!/usr/bin/env python3
"""Studio server — live design viewer for the 3d-print-studio repo.

Stdlib-only. Serves the three.js viewer and a small JSON API over projects/.

    .venv/bin/python studio/server.py [--port 8765]

Endpoints:
    GET  /                                  viewer page
    GET  /static/<path>                     assets (vendored three.js etc.)
    GET  /api/projects                      list projects
    GET  /api/projects/<n>/status           mtimes of model parts + refs (poll target)
    GET  /api/projects/<n>/manifest         parts + display colors
    GET  /api/projects/<n>/model/<file>     raw STL bytes
    GET  /api/projects/<n>/info             trimesh stats (cached by mtime)
    GET  /api/projects/<n>/refs             list reference images
    GET  /api/projects/<n>/refs/<file>      image bytes
    POST /api/projects/<n>/refs?name=<f>    upload image (raw body)
    POST /api/projects/<n>/capture          save viewer screenshot (raw PNG body)
    GET  /api/projects/<n>/files            every viewable STL in the project
    GET  /api/projects/<n>/file?rel=<rel>   raw bytes of one whitelisted STL
    POST /api/projects/<n>/generate         {"subject", "provider"?, "style"?} -> images into refs/
    POST /api/projects/<n>/make3d           {"image": "refs/x.png"} -> spawn Claude to build the model
    GET  /api/projects/<n>/make3d           status of the running/last build
    POST /api/projects/<n>/colors           {"<part file>": "#hex", ...} -> parts/parts.json

Image generation ("generate") providers:
    nano   Google Nano Banana (gemini-2.5-flash-image). Needs a key in
           $GEMINI_API_KEY or ~/.config/3d-prints/gemini_key. High quality, ~5-10 s.
    comfy  The local ComfyUI (Z-Image Turbo). Free, ~25 s. Probed on ports
           8000/8188/8189 — NOTE one known ComfyUI install runs on 8000, and comfy-cli's
           "running: false" is not authoritative about it.
    auto   nano if a key exists, else comfy.
"""
import argparse
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(REPO, "studio", "static")
PROJECTS = os.path.join(REPO, "projects")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MESH_EXTS = {".stl", ".3mf"}
MAX_DOWNLOAD = 250 * 1024 * 1024
SLICER_APP = "Creality Print"
MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".stl": "application/octet-stream",
}

# Deterministic display palette for multi-part models without a parts.json.
PALETTE = ["#4a90d9", "#e2703a", "#4caf7d", "#b06ab3", "#d9a44a", "#5bc0be", "#c85a76", "#8a9a5b"]

_info_cache = {}          # path -> (mtime, dict)
_info_lock = threading.Lock()

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]*$")


def safe_name(name):
    """A single path component: no traversal, no hidden files, sane charset."""
    return bool(name) and SAFE_NAME.match(name) and ".." not in name


def project_dir(name):
    if not safe_name(name):
        return None
    d = os.path.join(PROJECTS, name)
    return d if os.path.isdir(d) else None


def model_parts(pdir):
    """What the viewer displays, in priority order:
    parts/*.stl (live multi-part) > model.stl (live) > newest final/*.stl > newest source/*.stl.
    Returns (rel_paths, role)."""
    parts_dir = os.path.join(pdir, "parts")
    if os.path.isdir(parts_dir):
        stls = sorted(f for f in os.listdir(parts_dir) if f.lower().endswith(".stl"))
        if stls:
            return [os.path.join("parts", f) for f in stls], "live"
    if os.path.isfile(os.path.join(pdir, "model.stl")):
        return ["model.stl"], "live"
    for sub in ("final", "source"):
        d = os.path.join(pdir, sub)
        if os.path.isdir(d):
            stls = [f for f in os.listdir(d) if f.lower().endswith(".stl")]
            if stls:
                newest = max(stls, key=lambda f: os.path.getmtime(os.path.join(d, f)))
                return [os.path.join(sub, newest)], sub
    return [], "none"


def part_color(pdir, rel, index):
    # parts.json may sit at the project root or next to the STLs in parts/
    base = os.path.basename(rel)
    for cfg in (os.path.join(pdir, "parts.json"),
                os.path.join(pdir, "parts", "parts.json")):
        if not os.path.isfile(cfg):
            continue
        try:
            with open(cfg) as f:
                colors = json.load(f)
            if base in colors:
                return colors[base]
        except Exception:
            pass
    return PALETTE[index % len(PALETTE)]


def mesh_info(path):
    """trimesh stats for one STL, cached by (path, mtime)."""
    mtime = os.path.getmtime(path)
    with _info_lock:
        hit = _info_cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
    import trimesh  # deferred: keep server startup instant
    info = {"file": os.path.basename(path)}
    try:
        m = trimesh.load(path, force="mesh")
        if isinstance(m, trimesh.Scene):
            m = trimesh.util.concatenate(tuple(m.dump()))
        ext = (m.bounds[1] - m.bounds[0]).tolist()
        info.update({
            "bbox_mm": [round(v, 2) for v in ext],
            "triangles": int(len(m.faces)),
            "vertices": int(len(m.vertices)),
            "watertight": bool(m.is_watertight),
            "winding_consistent": bool(m.is_winding_consistent),
            "fits_295": all(v <= 295.0 for v in ext),
        })
        try:
            info["bodies"] = int(len(m.split(only_watertight=False)))
        except Exception:
            info["bodies"] = None
        if m.is_watertight:
            info["volume_cm3"] = round(float(m.volume) / 1000.0, 1)
    except Exception as e:
        info["error"] = str(e)
    with _info_lock:
        _info_cache[path] = (mtime, info)
    return info


def unique_path(directory, name):
    """refs/foo.png, refs/foo_2.png, ... — never overwrite."""
    os.makedirs(directory, exist_ok=True)
    base, ext = os.path.splitext(name)
    path, n = os.path.join(directory, name), 2
    while os.path.exists(path):
        path = os.path.join(directory, f"{base}_{n}{ext}")
        n += 1
    return path


def maybe_seed_live_model(pdir, path):
    """If an uploaded STL arrives and the project has no live model yet,
    copy it in as model.stl so the viewer shows it immediately."""
    if path.lower().endswith(".stl") and model_parts(pdir)[1] not in ("live",):
        import shutil
        shutil.copyfile(path, os.path.join(pdir, "model.stl"))
        return {"live_model": "model.stl"}
    return {}


def fetch_url(remote):
    """Download a public URL (size-capped). Returns (bytes, filename)."""
    import urllib.request
    req = urllib.request.Request(remote, headers={"User-Agent": "3d-print-studio/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read(MAX_DOWNLOAD + 1)
        if len(data) > MAX_DOWNLOAD:
            raise ValueError("file exceeds 250MB cap")
        name = os.path.basename(urlparse(remote).path) or "download"
        if "." not in name:
            ctype = resp.headers.get("Content-Type", "").split(";")[0].strip()
            name += {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
                     "image/gif": ".gif", "model/stl": ".stl"}.get(ctype, "")
        return data, re.sub(r"[^A-Za-z0-9._-]", "_", name)


def list_refs(pdir):
    refs_dir = os.path.join(pdir, "refs")
    out = []
    if os.path.isdir(refs_dir):
        for f in sorted(os.listdir(refs_dir)):
            p = os.path.join(refs_dir, f)
            if os.path.isfile(p) and os.path.splitext(f)[1].lower() in IMAGE_EXTS:
                out.append({"file": f, "mtime": os.path.getmtime(p)})
    return out


# ---------------------------------------------------------------------------
# image generation (Nano Banana / local ComfyUI) + "make me 3D" Claude jobs
# ---------------------------------------------------------------------------

MAKE3D_TIMEOUT_S = 18 * 60   # a build past this is wedged, not thorough
# Sonnet turns a 12-18 min build into a 5-8 min one with the same skills and
# contract — for a child waiting, speed beats the last few percent of polish.
# Override with STUDIO_MAKE3D_MODEL=opus (or any model name) and restart.
MAKE3D_MODEL = os.environ.get("STUDIO_MAKE3D_MODEL", "sonnet")
GEMINI_KEY_FILE = os.path.expanduser("~/.config/3d-prints/gemini_key")
GEMINI_MODEL = os.environ.get("STUDIO_NANO_MODEL", "gemini-2.5-flash-image")
COMFY_PORTS = (8000, 8188, 8189)   # one known install is on 8000; comfy-cli lies about it

# One image, three views — a turnaround sheet is what image-to-model wants.
TURNAROUND_PROMPT = (
    "A reference sheet for a 3D-printable toy of {subject}: one single image on a "
    "plain solid white background showing the SAME {subject} three times in a row — "
    "front view, side profile view, and three-quarter view. Cute chunky toy style "
    "with thick solid limbs, no thin or fragile parts, simple bold shapes, flat even "
    "colours, no shading on the background, no text, no watermark. The three views "
    "are consistent with each other, evenly spaced, same size."
)
# Flat colour sticker — what make_coin.py traces best: few flat colours, no shading.
STICKER_PROMPT = (
    "A cute flat sticker illustration of {subject} on a plain pure white background. "
    "Exactly three or four flat solid colours, thick bold chunky shapes, completely "
    "flat colour fill, no shading, no gradients, no outlines, no texture, single "
    "subject centred and filling about 70 percent of the square frame, simple "
    "toy-like proportions, crisp hard edges, die-cut sticker style."
)
# Solid silhouette — what make_chip.py wants. cfg=1 on comfy: positive phrasing only.
CHIP_PROMPT = (
    "A bold flat silhouette icon of {subject}. Pure white solid shape on a pure "
    "black background. One single filled silhouette with crisp hard edges. Chunky "
    "simple proportions with thick limbs, every part broad and solid. Centred, "
    "filling about 65 percent of the square frame with an even margin all around. "
    "Flat vector sticker style, completely solid fill, uniform white, instantly "
    "readable as a tiny stamp at thumbnail size."
)


def gemini_key():
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    if k:
        return k
    try:
        with open(GEMINI_KEY_FILE) as f:
            return f.read().strip()
    except OSError:
        return ""


def gen_nano(prompt, timeout=90):
    """One image from Nano Banana. Returns PNG/JPEG bytes."""
    import base64
    import urllib.request
    key = gemini_key()
    if not key:
        raise RuntimeError(
            f"no Nano Banana key — put it in $GEMINI_API_KEY or {GEMINI_KEY_FILE}")
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"],
                             "imageConfig": {"aspectRatio": "1:1"}},
    }).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}"
        ":generateContent",
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.load(r)
    for cand in resp.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            blob = part.get("inlineData", {}).get("data")
            if blob:
                return base64.b64decode(blob)
    raise RuntimeError("Nano Banana returned no image "
                       f"(finishReason: {resp.get('candidates', [{}])[0].get('finishReason')})")


def comfy_port():
    import urllib.request
    for p in COMFY_PORTS:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{p}/system_stats", timeout=3):
                return p
        except OSError:
            continue
    return None


def gen_comfy(prompt, timeout=240):
    """One image from the local ComfyUI (Z-Image Turbo). Returns image bytes."""
    import time
    import urllib.request
    port = comfy_port()
    if port is None:
        raise RuntimeError("no local ComfyUI answering on " + "/".join(map(str, COMFY_PORTS)))
    seed = int.from_bytes(os.urandom(4), "big") % (2 ** 31)
    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": "z_image_turbo_bf16.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": "qwen_3_4b.safetensors", "type": "lumina2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "z_image_ae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptySD3LatentImage", "inputs": {
            "width": 1024, "height": 1024, "batch_size": 1}},
        "7": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
        "8": {"class_type": "KSampler", "inputs": {
            "model": ["7", 0], "positive": ["4", 0], "negative": ["5", 0],
            "latent_image": ["6", 0], "seed": seed, "steps": 8, "cfg": 1.0,
            "sampler_name": "res_multistep", "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {
            "images": ["9", 0], "filename_prefix": "studio_gen"}},
    }

    def call(path, data=None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}",
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Content-Type": "application/json"} if data is not None else {})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)

    pid = call("/prompt", {"prompt": wf})["prompt_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = call(f"/history/{pid}")
        if pid in h:
            if h[pid].get("status", {}).get("status_str") == "error":
                raise RuntimeError("ComfyUI execution error")
            for node in h[pid].get("outputs", {}).values():
                for img in node.get("images", []):
                    from urllib.parse import urlencode
                    q = urlencode({"filename": img["filename"],
                                   "subfolder": img.get("subfolder", ""),
                                   "type": img.get("type", "output")})
                    with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/view?{q}", timeout=120) as r:
                        return r.read()
        time.sleep(1.5)
    raise RuntimeError("timed out waiting for ComfyUI")


def generate_images(pdir, subject, provider="auto", style="turnaround", count=None):
    """Generate candidate images into refs/. Returns (files, provider_used, errors)."""
    if provider == "auto":
        provider = "nano" if gemini_key() else "comfy"
    prompt = {"chip": CHIP_PROMPT, "sticker": STICKER_PROMPT}.get(
        style, TURNAROUND_PROMPT).format(subject=subject)
    n = count or (3 if provider == "nano" else 2)
    gen = gen_nano if provider == "nano" else gen_comfy

    slug = re.sub(r"[^a-z0-9]+", "_", subject.lower()).strip("_")[:32] or "idea"
    results, errors = [None] * n, []

    def worker(i):
        try:
            results[i] = gen(prompt)
        except Exception as e:  # collect, don't die — partial results still count
            errors.append(str(e))

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(n)]
    # comfy is a single queue — parallel submits just serialise; thread anyway
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=300)

    files = []
    for blob in results:
        if not blob:
            continue
        ext = ".png" if blob[:8] == b"\x89PNG\r\n\x1a\n" else ".jpg"
        path = unique_path(os.path.join(pdir, "refs"), f"gen_{slug}{ext}")
        with open(path, "wb") as f:
            f.write(blob)
        files.append(os.path.basename(path))
    return files, provider, errors


# -- "Make me 3D": one Claude build job per project -------------------------
_jobs = {}                 # project name -> {proc, log, image, started}
_jobs_lock = threading.Lock()

MAKE3D_PROMPT = """You are working in the 3d-print-studio repo at {repo}. Read AGENTS.md first and follow its contract.

A child chose the reference image projects/{project}/refs/{image} and pressed "Make me 3D" in the studio. Build them a printable model of what the image shows.

Use the repo's skills — they auto-load from .claude/skills/ and they are the house method:
image-to-model to interpret the picture, stl-prep (meshtools.py) for inspection/repair/
orientation, design-studio for the design.py conventions and hot-reload contract,
k2-supports to design AWAY from needing supports, k2-slicing for the print profile you
state at the end.

Requirements:
- Write projects/{project}/design.py (parametric, trimesh/shapely, dimensions as named constants) and run it with .venv/bin/python to produce projects/{project}/model.stl.
- EXPORT EARLY, THEN REFINE. A child is watching the live viewer: produce a rough blocked-out model.stl within your first few actions, then iterate and re-export as you improve it. Never work silently for many minutes with nothing on disk.
- ALSO export the model split into 2-4 separate bodies by colour region as projects/{project}/parts/*.stl plus a projects/{project}/parts/parts.json mapping each part filename to a sensible display hex colour. The studio shows parts/ live and the child paints each part separately — a single merged mesh cannot be painted.
- Bed coordinates, Z >= 0, flat stable base, largest dimension 60-90 mm, every feature >= 1.2 mm thick, watertight (verify and state it), printable in PLA with NO supports.
- This is a toy for young kids: chunky, robust, friendly. No thin spikes.
- Do not touch any other project. Keep your final answer to a few lines: what you built, the size, watertight yes/no.
"""


def start_make3d(pname, pdir, image):
    import subprocess
    with _jobs_lock:
        job = _jobs.get(pname)
        if job and job["proc"].poll() is None:
            return {"error": "a build is already running for this project"}
        log_path = os.path.join(pdir, ".make3d.log")
        log = open(log_path, "w")
        prompt = MAKE3D_PROMPT.format(repo=REPO, project=pname, image=image)
        try:
            # --strict-mcp-config with no --mcp-config: no MCP servers at all.
            # A build job needs none, they slow startup, and a hung MCP
            # handshake stalled a build for 27 minutes once.
            proc = subprocess.Popen(
                ["claude", "-p", prompt, "--permission-mode", "bypassPermissions",
                 "--strict-mcp-config", "--model", MAKE3D_MODEL],
                cwd=REPO, stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True)
        except FileNotFoundError:
            log.close()
            return {"error": "claude CLI not found on PATH"}
        job = {"proc": proc, "log": log_path, "image": image,
               "started": __import__("time").time(), "timed_out": False}

        def watchdog():
            if proc.poll() is None:
                job["timed_out"] = True
                proc.terminate()
        threading.Timer(MAKE3D_TIMEOUT_S, watchdog).start()
        _jobs[pname] = job
        return {"started": True, "pid": proc.pid}


def make3d_status(pname):
    with _jobs_lock:
        job = _jobs.get(pname)
    if not job:
        return {"state": "idle"}
    rc = job["proc"].poll()
    tail = ""
    try:
        with open(job["log"]) as f:
            tail = f.read()[-2000:]
    except OSError:
        pass
    pdir = os.path.join(PROJECTS, pname)
    wrote = any(
        os.path.isfile(f) and os.path.getmtime(f) > job["started"]
        for f in (os.path.join(pdir, "design.py"), os.path.join(pdir, "model.stl")))
    return {"state": "running" if rc is None else "done",
            "exit": rc, "image": job["image"],
            "elapsed": round(__import__("time").time() - job["started"]),
            "timed_out": job.get("timed_out", False),
            "wrote_files": wrote,
            "log_tail": tail}


def creation_project(src, image):
    """Every build gets its OWN project, named after the image, so creations
    never overwrite each other (a dragon build once ate the rocket). Same
    image again -> same project (a retry); fresh image -> slug_2, slug_3...
    Returns (name, dir, image_path) with the image copied in."""
    slug = re.sub(r"^gen_", "", os.path.splitext(image)[0])
    slug = re.sub(r"_\d+$", "", slug)
    slug = re.sub(r"[^a-z0-9_]", "", slug.lower()).strip("_")[:40] or "creation"
    target, n = slug, 2
    while True:
        tdir = os.path.join(PROJECTS, target)
        if not os.path.isdir(tdir):
            break
        has_img = os.path.isfile(os.path.join(tdir, "refs", image))
        marker = os.path.join(tdir, ".creation")
        has_img = os.path.isfile(os.path.join(tdir, "refs", image))
        # empty marker = auto-created coin/build project: retry in place.
        # Non-empty marker = LEGACY, a hand-built model
        # that a coin rebuild must NEVER overwrite: fall through to slug_2.
        if os.path.isfile(marker) and os.path.getsize(marker) == 0 and has_img:
            with _jobs_lock:
                j = _jobs.get(target)
            if not (j and j["proc"].poll() is None):
                break
        target = f"{slug}_{n}"
        n += 1
    tdir = os.path.join(PROJECTS, target)
    os.makedirs(os.path.join(tdir, "refs"), exist_ok=True)
    open(os.path.join(tdir, ".creation"), "w").close()
    dst = os.path.join(tdir, "refs", image)
    if not os.path.isfile(dst):
        import shutil
        shutil.copyfile(src, dst)
    return target, tdir, dst


def list_files(pdir):
    """Every STL a person might want to look at, grouped for the sidebar."""
    out = []
    def add(rel, kind):
        p = os.path.join(pdir, rel)
        out.append({"rel": rel, "kind": kind, "size": os.path.getsize(p),
                    "mtime": os.path.getmtime(p)})
    if os.path.isfile(os.path.join(pdir, "model.stl")):
        add("model.stl", "live")
    for sub, kind in (("parts", "part"), ("final", "final"), ("source", "source")):
        d = os.path.join(pdir, sub)
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                if f.lower().endswith(".stl"):
                    add(os.path.join(sub, f), kind)
    return out


def safe_rel_stl(pdir, rel):
    """Validate a rel path from list_files — no traversal, STL only."""
    if not rel or ".." in rel or rel.startswith("/") or not rel.lower().endswith(".stl"):
        return None
    parts_ = rel.split("/")
    if len(parts_) == 1 and parts_[0] == "model.stl":
        pass
    elif len(parts_) == 2 and parts_[0] in ("parts", "final", "source") and safe_name(parts_[1]):
        pass
    else:
        return None
    p = os.path.join(pdir, rel)
    return p if os.path.isfile(p) else None


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quieter: only non-poll requests
        if "/status" not in (args[0] if args else ""):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---- helpers -------------------------------------------------------
    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, code, msg):
        self.send_json({"error": msg}, code)

    def send_file(self, path, download_name=None):
        if not os.path.isfile(path):
            return self.send_error_json(404, "not found")
        ext = os.path.splitext(path)[1].lower()
        size = os.path.getsize(path)
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                self.wfile.write(chunk)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0 or length > 200 * 1024 * 1024:
            return None
        return self.rfile.read(length)

    # ---- routing -------------------------------------------------------
    def do_GET(self):
        try:
            self.route("GET")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        try:
            self.route("POST")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def route(self, method):
        url = urlparse(self.path)
        parts = [unquote(p) for p in url.path.split("/") if p]

        if method == "GET" and not parts:
            return self.send_file(os.path.join(STATIC, "index.html"))

        if method == "GET" and parts[0] == "static":
            rel = parts[1:]
            if not all(safe_name(p) for p in rel):
                return self.send_error_json(400, "bad path")
            return self.send_file(os.path.join(STATIC, *rel))

        # POST /api/server/restart — re-exec in place so code edits take effect
        # without hunting the PID (kill-style commands are awkward to automate).
        if method == "POST" and parts[:2] == ["api", "server"] \
                and len(parts) == 3 and parts[2] == "restart":
            self.send_json({"restarting": True})
            threading.Timer(0.4, lambda: os.execv(
                sys.executable, [sys.executable, os.path.abspath(__file__)]
                + sys.argv[1:])).start()
            return None

        # GET /api/library — the picture pool, each image resolved to the
        # creation project it became (or null). One picture -> one model.
        if method == "GET" and parts[:2] == ["api", "library"] and len(parts) == 2:
            lib = os.path.join(PROJECTS, "library")
            imgs = list_refs(lib)
            # index creation projects once: name -> (refs set, has_model, ref_count)
            idx = {}
            for name in os.listdir(PROJECTS):
                pd = os.path.join(PROJECTS, name)
                if name == "library" or not os.path.isdir(pd):
                    continue
                if not os.path.isfile(os.path.join(pd, ".creation")):
                    continue
                refs = {r["file"] for r in list_refs(pd)}
                has_model = bool(model_parts(pd)[0])
                idx[name] = (refs, has_model, len(refs))
            out = []
            for im in imgs:
                f = im["file"]
                slug = re.sub(r"^gen_", "", os.path.splitext(f)[0])
                slug = re.sub(r"_\d+$", "", slug)
                slug = re.sub(r"[^a-z0-9_]", "", slug.lower()).strip("_")
                proj = None
                # exact slug (or slug_N) match first, then most-specific holder
                for cand, (refs, hm, _) in idx.items():
                    if f in refs and hm and (cand == slug or
                                             re.fullmatch(re.escape(slug) + r"_\d+", cand)):
                        proj = cand
                        break
                if proj is None:
                    holders = [(n, c) for n, (refs, hm, c) in idx.items()
                               if f in refs and hm]
                    if holders:
                        proj = min(holders, key=lambda t: t[1])[0]
                out.append({"file": f, "mtime": im["mtime"], "project": proj,
                            "url": f"/api/projects/library/refs/{f}"})
            return self.send_json({"images": out})

        if parts[0] != "api" or len(parts) < 2 or parts[1] != "projects":
            return self.send_error_json(404, "unknown route")

        # /api/projects
        if len(parts) == 2 and method == "GET":
            os.makedirs(PROJECTS, exist_ok=True)
            out = []
            for name in sorted(os.listdir(PROJECTS)):
                pdir = os.path.join(PROJECTS, name)
                if os.path.isdir(pdir) and not name.startswith("."):
                    mp, role = model_parts(pdir)
                    out.append({"name": name, "has_model": bool(mp),
                                "part_count": len(mp), "role": role})
            return self.send_json({"projects": out})

        # POST /api/projects  {"name": "..."} — create a project
        if len(parts) == 2 and method == "POST":
            body = self.read_body()
            try:
                name = json.loads(body)["name"].strip().lower().replace(" ", "_")
            except Exception:
                return self.send_error_json(400, "body must be JSON: {\"name\": ...}")
            name = re.sub(r"[^a-z0-9_-]", "", name)
            if not safe_name(name):
                return self.send_error_json(400, "bad project name")
            pdir = os.path.join(PROJECTS, name)
            existed = os.path.isdir(pdir)
            os.makedirs(os.path.join(pdir, "refs"), exist_ok=True)
            return self.send_json({"name": name, "created": not existed})

        pdir = project_dir(parts[2])
        if pdir is None:
            return self.send_error_json(404, "no such project")
        sub = parts[3] if len(parts) > 3 else None
        pname = parts[2]

        if method == "GET":
            if sub == "status":
                items = []
                mp, role = model_parts(pdir)
                for rel in mp:
                    p = os.path.join(pdir, rel)
                    st = os.stat(p)
                    items.append({"file": rel, "mtime": st.st_mtime, "size": st.st_size})
                return self.send_json({"parts": items, "role": role, "refs": list_refs(pdir)})

            if sub == "manifest":
                out = []
                mp, role = model_parts(pdir)
                for i, rel in enumerate(mp):
                    out.append({
                        "file": rel,
                        "url": f"/api/projects/{pname}/model/{os.path.basename(rel)}",
                        "color": part_color(pdir, rel, i),
                    })
                return self.send_json({"parts": out, "role": role})

            if sub == "model" and len(parts) == 5:
                # whitelist against current manifest — no arbitrary reads
                for rel in model_parts(pdir)[0]:
                    if os.path.basename(rel) == parts[4]:
                        return self.send_file(os.path.join(pdir, rel))
                return self.send_error_json(404, "no such part")

            if sub == "info":
                infos = [mesh_info(os.path.join(pdir, rel)) for rel in model_parts(pdir)[0]]
                combined = {}
                if infos and not any("error" in i for i in infos):
                    bbox = [max(i["bbox_mm"][k] for i in infos) for k in range(3)]
                    combined = {
                        "triangles": sum(i["triangles"] for i in infos),
                        "watertight": all(i["watertight"] for i in infos),
                        "fits_295": all(i["fits_295"] for i in infos),
                        "bbox_mm": bbox if len(infos) > 1 else infos[0]["bbox_mm"],
                    }
                return self.send_json({"parts": infos, "combined": combined})

            if sub == "refs" and len(parts) == 4:
                refs = [{**r, "url": f"/api/projects/{pname}/refs/{r['file']}"}
                        for r in list_refs(pdir)]
                return self.send_json({"refs": refs})

            if sub == "refs" and len(parts) == 5:
                if not safe_name(parts[4]):
                    return self.send_error_json(400, "bad name")
                return self.send_file(os.path.join(pdir, "refs", parts[4]))

            if sub == "files":
                return self.send_json({"files": list_files(pdir),
                                       "nano_key": bool(gemini_key())})

            if sub == "file":
                rel = parse_qs(url.query).get("rel", [""])[0]
                p = safe_rel_stl(pdir, rel)
                if not p:
                    return self.send_error_json(400, "bad rel path")
                return self.send_file(p)

            if sub == "make3d":
                return self.send_json(make3d_status(pname))

            return self.send_error_json(404, "unknown route")

        # POST
        if sub == "refs":
            q = parse_qs(url.query)
            name = os.path.basename(q.get("name", ["upload.png"])[0])
            name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
            if not safe_name(name) or os.path.splitext(name)[1].lower() not in IMAGE_EXTS:
                return self.send_error_json(400, "bad image name")
            body = self.read_body()
            if body is None:
                return self.send_error_json(400, "empty body")
            refs_dir = os.path.join(pdir, "refs")
            os.makedirs(refs_dir, exist_ok=True)
            base, ext = os.path.splitext(name)
            path, n = os.path.join(refs_dir, name), 2
            while os.path.exists(path):
                path = os.path.join(refs_dir, f"{base}_{n}{ext}")
                n += 1
            with open(path, "wb") as f:
                f.write(body)
            return self.send_json({"path": os.path.relpath(path, REPO)})

        if sub == "source":
            # raw-body upload of a mesh file into source/
            q = parse_qs(url.query)
            name = os.path.basename(q.get("name", ["upload.stl"])[0])
            name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
            ext = os.path.splitext(name)[1].lower()
            if not safe_name(name) or ext not in MESH_EXTS:
                return self.send_error_json(400, "expected a .stl or .3mf filename")
            body = self.read_body()
            if body is None:
                return self.send_error_json(400, "empty body")
            path = unique_path(os.path.join(pdir, "source"), name)
            with open(path, "wb") as f:
                f.write(body)
            out = {"path": os.path.relpath(path, REPO)}
            out.update(maybe_seed_live_model(pdir, path))
            return self.send_json(out)

        if sub == "import-url":
            # {"url": "https://..."} — fetch a public image or mesh onto disk
            try:
                remote = json.loads(self.read_body())["url"].strip()
            except Exception:
                return self.send_error_json(400, "body must be JSON: {\"url\": ...}")
            if not remote.startswith(("http://", "https://")):
                return self.send_error_json(400, "url must be http(s)")
            try:
                data, name = fetch_url(remote)
            except Exception as e:
                return self.send_error_json(502, f"download failed: {e}")
            ext = os.path.splitext(name)[1].lower()
            if ext in IMAGE_EXTS:
                path = unique_path(os.path.join(pdir, "refs"), name)
            elif ext in MESH_EXTS:
                path = unique_path(os.path.join(pdir, "source"), name)
            else:
                return self.send_error_json(400,
                    f"unsupported type '{ext or 'unknown'}' — need an image, .stl, or .3mf")
            with open(path, "wb") as f:
                f.write(data)
            out = {"path": os.path.relpath(path, REPO), "bytes": len(data)}
            if ext in MESH_EXTS:
                out.update(maybe_seed_live_model(pdir, path))
            return self.send_json(out)

        if sub == "slice":
            # open the currently displayed model files in Creality Print
            mp, role = model_parts(pdir)
            if not mp:
                return self.send_error_json(400, "project has no model to slice")
            paths = [os.path.join(pdir, rel) for rel in mp]
            import subprocess
            try:
                r = subprocess.run(["open", "-a", SLICER_APP, *paths],
                                   capture_output=True, text=True, timeout=15)
            except Exception as e:
                return self.send_error_json(500, f"could not launch slicer: {e}")
            if r.returncode != 0:
                return self.send_error_json(500,
                    f"'{SLICER_APP}' failed to open: {r.stderr.strip() or 'is it installed?'}")
            return self.send_json({"opened": [os.path.relpath(p, REPO) for p in paths],
                                   "app": SLICER_APP, "role": role})

        if sub == "generate":
            try:
                body = json.loads(self.read_body())
                subject = body["subject"].strip()
                assert subject
            except Exception:
                return self.send_error_json(400, 'body must be JSON: {"subject": ...}')
            provider = body.get("provider", "auto")
            style = body.get("style", "turnaround")
            count = body.get("count")
            if provider not in ("auto", "nano", "comfy"):
                return self.send_error_json(400, "provider must be auto|nano|comfy")
            files, used, errors = generate_images(pdir, subject, provider, style, count)
            if not files:
                return self.send_error_json(
                    502, "; ".join(dict.fromkeys(errors)) or "generation failed")
            return self.send_json({
                "provider": used, "errors": errors,
                "images": [{"file": f, "url": f"/api/projects/{pname}/refs/{f}"}
                           for f in files]})

        if sub == "make3d" and len(parts) == 5 and parts[4] == "cancel":
            with _jobs_lock:
                job = _jobs.get(pname)
            if not job or job["proc"].poll() is not None:
                return self.send_error_json(404, "no build is running")
            job["proc"].terminate()
            return self.send_json({"cancelled": True})

        if sub == "make3d":
            try:
                image = os.path.basename(json.loads(self.read_body())["image"])
            except Exception:
                return self.send_error_json(400, 'body must be JSON: {"image": ...}')
            src = os.path.join(pdir, "refs", image)
            if not safe_name(image) or not os.path.isfile(src):
                return self.send_error_json(404, f"refs/{image} does not exist")

            target, tdir, dst = creation_project(src, image)
            out = start_make3d(target, tdir, image)
            if "error" not in out:
                out["project"] = target
                out["image"] = image
            return self.send_json(out, 409 if "error" in out else 200)

        if sub == "coin":
            # image -> traced multi-colour coin, deterministically, in seconds.
            # No Claude involved — this is the kids' default path.
            try:
                image = os.path.basename(json.loads(self.read_body())["image"])
            except Exception:
                return self.send_error_json(400, 'body must be JSON: {"image": ...}')
            src = os.path.join(pdir, "refs", image)
            if not safe_name(image) or not os.path.isfile(src):
                return self.send_error_json(404, f"refs/{image} does not exist")
            target, tdir, dst = creation_project(src, image)
            import subprocess
            r = subprocess.run(
                [os.path.join(REPO, ".venv", "bin", "python"),
                 os.path.join(PROJECTS, "coin_board", "make_coin.py"),
                 dst, "--name", target, "--out", tdir],
                capture_output=True, text=True, timeout=120, cwd=REPO)
            if r.returncode != 0:
                return self.send_error_json(
                    500, "coin failed: " + (r.stdout + r.stderr).strip()[-300:])
            return self.send_json({"project": target, "image": image,
                                   "report": r.stdout.strip()[-600:]})

        if sub == "colors":
            try:
                incoming = json.loads(self.read_body())
                assert isinstance(incoming, dict)
            except Exception:
                return self.send_error_json(400, 'body must be JSON: {"part.stl": "#hex"}')
            cfg_dir = os.path.join(pdir, "parts")
            cfg = os.path.join(cfg_dir, "parts.json") if os.path.isdir(cfg_dir) \
                else os.path.join(pdir, "parts.json")
            current = {}
            if os.path.isfile(cfg):
                try:
                    with open(cfg) as f:
                        current = json.load(f)
                except Exception:
                    current = {}
            for k, v in incoming.items():
                if safe_name(os.path.basename(k)) and re.match(r"^#[0-9a-fA-F]{6}$", str(v)):
                    current[os.path.basename(k)] = v
            with open(cfg, "w") as f:
                json.dump(current, f, indent=2)
            return self.send_json({"saved": cfg and os.path.relpath(cfg, REPO),
                                   "colors": current})

        if sub == "capture":
            body = self.read_body()
            if body is None:
                return self.send_error_json(400, "empty body")
            refs_dir = os.path.join(pdir, "refs")
            os.makedirs(refs_dir, exist_ok=True)
            n = 1
            while os.path.exists(os.path.join(refs_dir, f"capture_{n}.png")):
                n += 1
            path = os.path.join(refs_dir, f"capture_{n}.png")
            with open(path, "wb") as f:
                f.write(body)
            return self.send_json({"path": os.path.relpath(path, REPO)})

        return self.send_error_json(404, "unknown route")


def main():
    ap = argparse.ArgumentParser(description="3D Print Studio server")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    os.makedirs(PROJECTS, exist_ok=True)
    # the shared picture library: every generated/imported image lands here,
    # and creations are spawned FROM it — one picture -> one model
    os.makedirs(os.path.join(PROJECTS, "library", "refs"), exist_ok=True)
    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as e:
        sys.exit(f"Could not bind port {args.port} ({e}). Try --port <other>.")
    print(f"Studio: http://localhost:{args.port}/")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
