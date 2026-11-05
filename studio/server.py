#!/usr/bin/env python3
"""Studio server — the 3D Print Studio's live design viewer and kid flow.

Stdlib-only. Serves the three.js viewer and a small JSON API over the projects
directory (default <repo>/projects).

    .venv/bin/python studio/server.py [--port 8765] [--projects <dir>]

Settings come from studio/config.py (studio.config.json < environment), read
per request — re-running install.sh or editing the file needs no restart.
On first start an empty projects directory is seeded from examples/.

Loopback only: requests must carry a localhost Host header, and a browser
POST must come from the studio's own page, same host and port (any website,
or another local server, can otherwise POST here, and "Make me 3D" runs
Claude Code with bypassPermissions). A port-forwarder's own hostname can be
allowed with STUDIO_ALLOWED_HOSTS=name[,name].

Endpoints:
    GET  /                                  viewer page
    GET  /static/<path>                     assets (vendored three.js etc.)
    GET  /api/setup                         config + readiness checks (config.checks)
    POST /api/server/restart                re-exec in place (picks up code edits)
    GET  /api/projects                      list projects
    POST /api/projects                      {"name": ...} -> create a project
    GET  /api/projects/<n>/status           mtimes of model parts + refs (poll target)
    GET  /api/projects/<n>/manifest         parts + display colors
    GET  /api/projects/<n>/model/<file>     raw STL bytes
    GET  /api/projects/<n>/info             trimesh stats (cached by mtime); fits_bed
                                            is checked against the printer envelope
    GET  /api/projects/<n>/refs             list reference images
    GET  /api/projects/<n>/refs/<file>      image bytes
    POST /api/projects/<n>/refs?name=<f>    upload image (raw body)
    POST /api/projects/<n>/source?name=<f>  upload a mesh into source/ (raw body)
    POST /api/projects/<n>/import-url       {"url": ...} -> fetch an image or mesh
    POST /api/projects/<n>/capture          save viewer screenshot (raw PNG body)
    GET  /api/projects/<n>/files            every viewable STL + the picture backend
    GET  /api/projects/<n>/file?rel=<rel>   raw bytes of one whitelisted STL
    POST /api/projects/<n>/generate         {"subject", "provider"?, "style"?, "count"?}
                                            -> `count` picture options into refs/
    POST /api/projects/<n>/make3d           {"image": "refs/x.png"} -> spawn Claude to build the model
    GET  /api/projects/<n>/make3d           status of the running/last build
    POST /api/projects/<n>/make3d/cancel    stop the running build
    POST /api/projects/<n>/coin             {"image": "refs/x.png"} -> traced multi-colour coin
    POST /api/projects/<n>/slice            open the model (or slice.json's files) in the slicer
    POST /api/projects/<n>/archive          move the project to projects/.archive/
    POST /api/projects/<n>/colors           {"<part file>": "#hex", ...} -> parts/parts.json
    GET  /api/library                       picture pool; each image lists its builds
                                            [{project, kind: coin|toy, has_model}] —
                                            one picture can have a coin AND a toy;
                                            building the same kind again = redo in place
    POST /api/library/archive               {"image": "<file>"} -> projects/.archive/library_refs/

Picture backends ("generate" provider; see studio/imagegen.py):
    claude   the user's own Claude Code CLI, headless, draws SVGs (Opus by default)
    comfyui  a local ComfyUI running Z-Image Turbo ("comfy" is an alias)
    nano     Google Nano Banana — needs a Gemini API key
    auto     config.resolve_backend: nano if a key exists, a running ComfyUI, else claude
"""
import argparse
import filecmp
import json
import os
import re
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

STUDIO = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(STUDIO)
STATIC = os.path.join(STUDIO, "static")
TOOLS = os.path.join(STUDIO, "tools")
EXAMPLES = os.path.join(REPO, "examples")

sys.path.insert(0, STUDIO)
import config                                                # noqa: E402
import imagegen                                              # noqa: E402
from imagegen import unique_path                             # noqa: E402

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MESH_EXTS = {".stl", ".3mf"}
MAX_DOWNLOAD = 250 * 1024 * 1024
MAX_SUBJECT = 200          # characters of a kid's request that reach a prompt
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


# Any web page the user visits can send a "simple" POST to localhost (a
# text/plain or bare body needs no CORS preflight), and a DNS-rebinding page
# can read the answers too. This server uploads pictures and then spawns
# Claude Code with bypassPermissions on them, so: loopback Host names only,
# and a browser POST must come from the studio's own origin. curl, the smoke
# test and agents send no Origin and are unaffected.
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _hostname(value):
    """'localhost:8765' -> 'localhost', '[::1]:8765' -> '::1',
    'http://127.0.0.1:8765' -> '127.0.0.1'."""
    value = (value or "").strip().lower()
    if "://" in value:
        value = urlparse(value).netloc
    if value.startswith("["):
        return value[1:value.find("]")] if "]" in value else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def _allowed_hosts():
    # STUDIO_ALLOWED_HOSTS="a.example,b.example": names a port-forwarder or
    # tunnel you set up yourself puts in the Host header
    return {h.strip().lower() for h in os.environ.get("STUDIO_ALLOWED_HOSTS", "").split(",")
            if h.strip()}


def _is_loopback(host):
    return host in LOOPBACK_HOSTS or host.endswith(".localhost") or host in _allowed_hosts()


def _same_origin(origin, host):
    """The Origin (the page) names the host and port the request was sent to.
    Any other local server is another site whatever name it is reached by: a
    page from localhost:3000 opened as evil.localhost:3000 and posting to
    evil.localhost:<studio port> differs from the studio only in the port."""
    try:
        o = urlparse(origin.strip())
        h = urlparse("//" + host.strip())
        oport = o.port or {"http": 80, "https": 443}.get(o.scheme)
        # a Host with no port reached port 80: this server speaks plain HTTP,
        # and a TLS tunnel in front of it is what STUDIO_ALLOWED_HOSTS is for
        return bool(o.hostname) and (o.hostname, oport) == (h.hostname, h.port or 80)
    except ValueError:              # a port that isn't a number
        return False


def request_refusal(headers, method):
    """None when the request may proceed, else why it was refused."""
    host = headers.get("Host")
    if host and not _is_loopback(_hostname(host)):
        return (f"Host '{host}' refused — open the studio at http://localhost:<port>/ "
                "(or add the name to STUDIO_ALLOWED_HOSTS)")
    if method != "GET":
        origin = headers.get("Origin")
        # a tunnel or port-forwarder may rewrite Host, so the exact names in
        # STUDIO_ALLOWED_HOSTS are the one exemption from matching it
        if (origin is not None and _hostname(origin) not in _allowed_hosts()
                and not (host and _same_origin(origin, host))):
            return "cross-site request refused"
        # The browser's own verdict, a backstop for a missing or odd Origin.
        # Chrome calls localhost:3000 -> localhost:8765 "same-site" (and
        # *.localhost the same), while the studio's own page sends "same-origin".
        site = headers.get("Sec-Fetch-Site")
        if site is not None and site.strip().lower() not in ("same-origin", "none"):
            return "cross-site request refused"
    return None


def projects_root(cfg=None):
    """The projects directory, looked up per request (config.projects_dir)."""
    return config.projects_dir(cfg or config.get())


def archive_dir(cfg=None):
    return os.path.join(projects_root(cfg), ".archive")   # hidden from listings and the API


def api_path(path):
    """A path for API responses: repo-relative when the projects dir lives in
    the repo (the default), else "projects/<...>" relative to the projects dir —
    never an absolute path, never a ../../ climb out of the repo."""
    path = os.path.abspath(path)
    try:
        if os.path.commonpath([path, REPO]) == REPO:
            return os.path.relpath(path, REPO)
    except ValueError:              # different drives (Windows)
        pass
    return os.path.join("projects", os.path.relpath(path, projects_root()))


def tool_python():
    """The repo's own interpreter for design.py / coin jobs (falls back to the
    one running the server, e.g. a test run before install)."""
    venv = os.path.join(REPO, ".venv", "bin", "python")
    return venv if os.path.exists(venv) else sys.executable


def project_dir(name):
    if not safe_name(name):
        return None
    d = os.path.join(projects_root(), name)
    return d if os.path.isdir(d) else None


def _projects_empty(root):
    """No project folders yet (files like README.md and hidden entries don't
    count; neither does a library with no pictures in it)."""
    for name in os.listdir(root):
        p = os.path.join(root, name)
        if name.startswith(".") or not os.path.isdir(p):
            continue
        if name == "library" and not list_refs(p):
            continue
        return False
    return True


def seed_projects(root):
    """First start only: an empty projects directory gets a copy of examples/
    (seed projects plus library/refs pictures, with their .creation markers),
    so a new user has something to look at and change. `.seeded` makes it
    once — deleting the examples later doesn't bring them back. Always makes
    sure the shared picture library exists. Returns the names copied."""
    os.makedirs(root, exist_ok=True)
    copied = []
    marker = os.path.join(root, ".seeded")
    if not os.path.exists(marker) and os.path.isdir(EXAMPLES) and _projects_empty(root):
        for name in sorted(os.listdir(EXAMPLES)):
            src = os.path.join(EXAMPLES, name)
            if os.path.isdir(src) and safe_name(name):
                shutil.copytree(src, os.path.join(root, name), dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns(
                                    "__pycache__", "*.pyc", ".DS_Store"))
                copied.append(name)
        if copied:
            open(marker, "w").close()
    # the shared picture library: every generated/imported image lands here,
    # and creations are spawned FROM it — one picture -> its coin and/or toy
    os.makedirs(os.path.join(root, "library", "refs"), exist_ok=True)
    return copied


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


def fits_envelope(bbox, envelope):
    """Per axis, against the configured printer's design envelope (255³ on the
    shipped K2 default: 260 bed minus margin). Computed per request, never
    cached with the mesh — the printer can change under a cached mesh."""
    return all(v <= e for v, e in zip(bbox, envelope))


def mesh_info(path):
    """trimesh stats for one STL, cached by (path, mtime). fits_bed is added by
    the caller against the current envelope."""
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


def maybe_seed_live_model(pdir, path):
    """If an uploaded STL arrives and the project has no live model yet,
    copy it in as model.stl so the viewer shows it immediately."""
    if path.lower().endswith(".stl") and model_parts(pdir)[1] not in ("live",):
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
# "Make me 3D" — the user's own Claude Code CLI, headless, one build per project
# ---------------------------------------------------------------------------
# Pictures are drawn by studio/imagegen.py (claude / comfyui / nano).

_jobs = {}                 # project name -> {proc, log, image, started}
_jobs_lock = threading.Lock()
CLAUDE_MISSING = ("Claude Code CLI not found — install it "
                  "(curl -fsSL https://claude.ai/install.sh | bash), "
                  "or set claude.bin in studio.config.json")

MAKE3D_PROMPT = """You are working in the 3D Print Studio repo at {repo}. Read AGENTS.md first and follow its contract.

A child chose the reference image {pdir}/refs/{image} and pressed "Make me 3D" in the studio. Build them a printable model of what the image shows.{svg_note}

Printer: {printer}, design envelope {env} mm (bed {bed} mm). The model must fit inside the envelope.

Use the repo's skills — they auto-load from .claude/skills/ (or read skills/*/SKILL.md) and they are the house method:
image-to-model to interpret the picture, stl-prep (skills/stl-prep/meshtools.py) for inspection/repair/
orientation, design-studio for the design.py conventions and hot-reload contract,
k2-supports to design AWAY from needing supports, k2-slicing for the print profile you
state at the end. The k2-* skills ship tuned for the Creality K2; where this printer differs, the printer facts above win.

Requirements:
- Write {pdir}/design.py (parametric, trimesh/shapely, dimensions as named constants) and run it with {python} to produce {pdir}/model.stl.
- EXPORT EARLY, THEN REFINE. A child is watching the live viewer: produce a rough blocked-out model.stl within your first few actions, then iterate and re-export as you improve it. Never work silently for many minutes with nothing on disk.
- ALSO export the model split into 2-4 separate bodies by colour region as {pdir}/parts/*.stl plus a {pdir}/parts/parts.json mapping each part filename to a sensible display hex colour. The studio shows parts/ live and the child paints each part separately — a single merged mesh cannot be painted.
- Bed coordinates, Z >= 0, flat stable base, largest dimension {size_lo}-{size_hi} mm, every feature >= 1.2 mm thick, watertight (verify and state it), printable in PLA with NO supports.
- This is a toy for children aged {ages}: chunky, robust, friendly. No thin spikes.
- Do not touch any other project. Keep your final answer to a few lines: what you built, the size, watertight yes/no.
"""


def _fmt_mm(dims):
    return "×".join(f"{v:g}" for v in dims)


def make3d_prompt(cfg, pdir, image, svg=None):
    env = config.envelope_mm(cfg)
    # the toy-sized target, shrunk for a printer too small for it
    hi = min(90.0, min(env))
    lo = round(hi * 2 / 3)                   # 60-90 mm on any printer that fits 90
    svg_note = ""
    if svg:
        svg_note = (f"\n\nThe picture was drawn as vector art: {svg} has its exact shapes and "
                    "colours (the PNG is a render of it). Read it when you need precise outlines "
                    "or the colour regions.")
    return MAKE3D_PROMPT.format(
        repo=REPO, pdir=pdir, image=image, svg_note=svg_note,
        printer=config.get_path(cfg, "printer.name") or "a 3D printer",
        env=_fmt_mm(env), bed=_fmt_mm(config.bed_mm(cfg)),
        size_lo=f"{lo:g}", size_hi=f"{hi:g}",
        ages=config.get_path(cfg, "kid.ages") or "5 to 9",
        python=tool_python())


def start_make3d(pname, pdir, image, cfg, svg=None):
    import subprocess
    import time
    with _jobs_lock:
        job = _jobs.get(pname)
        if job and job["proc"].poll() is None:
            return {"error": "a build is already running for this project"}
        binpath = config.claude_bin(cfg)
        if not binpath:
            return {"error": CLAUDE_MISSING}
        model = config.get_path(cfg, "claude.build_model") or "claude-opus-5-5"
        try:
            timeout_s = float(config.get_path(cfg, "claude.build_timeout_min") or 30) * 60
        except (TypeError, ValueError):     # a hand-edited "30 min" must not kill the build
            timeout_s = 30 * 60
        log_path = os.path.join(pdir, ".make3d.log")
        log = open(log_path, "w")
        prompt = make3d_prompt(cfg, pdir, image, svg)
        # --strict-mcp-config with no --mcp-config: no MCP servers at all.
        # A build job needs none, they slow startup, and a hung MCP
        # handshake stalled a build for 27 minutes once.
        cmd = [binpath, "-p", prompt, "--permission-mode", "bypassPermissions",
               "--strict-mcp-config", "--model", model]
        root = projects_root(cfg)
        try:
            inside = os.path.commonpath([os.path.abspath(root), REPO]) == REPO
        except ValueError:
            inside = False
        if not inside:
            cmd += ["--add-dir", root]       # projects live outside the repo cwd
        try:
            proc = subprocess.Popen(
                cmd, cwd=REPO, stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True)
        except OSError as error:
            # missing, not executable, or not a program at all: one readable
            # answer, never a crashed request — and the old toy left intact
            log.close()
            return {"error": f"could not run {binpath}: {error.strerror or error}"}
        # a redo: move stale part STLs to the archive so old and new bodies
        # never mix (model.stl stays visible until the build overwrites it).
        # Archived, not deleted: a redo that then fails must not cost the old
        # toy. Only now that the build is really running; Claude takes
        # seconds to write anything, so this can't race its first export.
        pparts = os.path.join(pdir, "parts")
        stale = [f for f in (os.listdir(pparts) if os.path.isdir(pparts) else [])
                 if f.lower().endswith(".stl")]
        if stale:
            # the build is already running: a full disk or an unwritable archive
            # must not orphan it (no watchdog, no cancel), so this can't raise
            try:
                dest = unique_path(os.path.join(archive_dir(cfg), "redo_parts"),
                                   f"{pname}_{int(time.time())}")
                os.makedirs(dest)
                for f in stale:
                    shutil.move(os.path.join(pparts, f), os.path.join(dest, f))
            except OSError as error:
                log.write(f"[studio] could not archive the old parts ({error}); "
                          "they stay in parts/ until the build replaces them\n")
                log.flush()
        job = {"proc": proc, "log": log_path, "image": image, "pdir": pdir,
               "started": time.time(), "timed_out": False, "timeout_s": timeout_s}

        def watchdog():
            if proc.poll() is None:
                job["timed_out"] = True
                proc.terminate()
        t = threading.Timer(timeout_s, watchdog)
        t.daemon = True
        t.start()
        _jobs[pname] = job
        return {"started": True, "pid": proc.pid, "model": model}


def make3d_status(pname):
    import time
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
    pdir = job.get("pdir") or os.path.join(projects_root(), pname)
    wrote = any(
        os.path.isfile(f) and os.path.getmtime(f) > job["started"]
        for f in (os.path.join(pdir, "design.py"), os.path.join(pdir, "model.stl")))
    return {"state": "running" if rc is None else "done",
            "exit": rc, "image": job["image"],
            "elapsed": round(time.time() - job["started"]),
            "timed_out": job.get("timed_out", False),
            "timeout_min": round(job.get("timeout_s", 0) / 60),
            "wrote_files": wrote,
            "log_tail": tail}


def creation_meta(pdir):
    """{"image": ..., "kind": "coin"|"toy"} for a creation project, {} if none."""
    try:
        with open(os.path.join(pdir, ".creation.json")) as f:
            m = json.load(f)
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}


def detect_kind(pdir):
    """Best guess for a legacy creation project with no .creation.json."""
    coin = os.path.isfile(os.path.join(pdir, "parts", "coin_body.stl"))
    toy = os.path.isfile(os.path.join(pdir, "design.py"))
    if coin and toy:
        return "mixed"      # the old one-project-per-image collision
    return "coin" if coin else ("toy" if toy else None)


def creation_project(src, image, kind):
    """Every build gets its OWN project per (image, kind), so creations never
    overwrite each other (a dragon build once ate the rocket) and one picture
    can have BOTH a coin and a toy. Same image+kind again -> the same project
    back — that IS the redo. `.creation.json` records the exact source image
    and kind; legacy projects (empty `.creation` marker, no json) are matched
    by their image copy + content, never a hand-built project (non-empty
    marker — hours of hand work a button must never overwrite).
    Returns (name, dir, image_path)."""
    root = projects_root()
    for name in sorted(os.listdir(root)):
        tdir = os.path.join(root, name)
        marker = os.path.join(tdir, ".creation")
        if not os.path.isdir(tdir) or not os.path.isfile(marker):
            continue
        meta = creation_meta(tdir)
        if meta:
            match = meta.get("image") == image and meta.get("kind") == kind
        else:
            match = (os.path.getsize(marker) == 0
                     and os.path.isfile(os.path.join(tdir, "refs", image))
                     and detect_kind(tdir) == kind)   # "mixed" never matches
        if not match:
            continue
        dst = os.path.join(tdir, "refs", image)
        if os.path.isfile(dst) and not filecmp.cmp(src, dst, shallow=False):
            # same NAME, different picture: archiving gen_dragon.png frees the
            # name, and the next dragon reused it — the redo then rebuilt the
            # OLD dragon from this project's copy. Not a redo: a fresh project.
            continue
        with _jobs_lock:
            j = _jobs.get(name)
        if j and j["proc"].poll() is None:
            continue                       # busy — a fresh project instead
        with open(os.path.join(tdir, ".creation.json"), "w") as f:
            json.dump({"image": image, "kind": kind}, f)   # backfill legacy
        if not os.path.isfile(dst):
            shutil.copyfile(src, dst)
        return name, tdir, dst

    # fresh project: <image slug>_<kind>, numbered on collision. The slug keeps
    # the image's trailing _N — stripping it once cross-wired gen_a_shark.png
    # and gen_a_shark_2.png into each other's projects.
    slug = re.sub(r"^gen_", "", os.path.splitext(image)[0])
    slug = re.sub(r"[^a-z0-9_]", "", slug.lower()).strip("_")[:40] or "creation"
    target, n = f"{slug}_{kind}", 2
    while os.path.isdir(os.path.join(root, target)):
        target = f"{slug}_{kind}_{n}"
        n += 1
    tdir = os.path.join(root, target)
    os.makedirs(os.path.join(tdir, "refs"), exist_ok=True)
    open(os.path.join(tdir, ".creation"), "w").close()
    with open(os.path.join(tdir, ".creation.json"), "w") as f:
        json.dump({"image": image, "kind": kind}, f)
    dst = os.path.join(tdir, "refs", image)
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
        if "/status" not in (str(args[0]) if args else ""):  # log_error passes an HTTPStatus
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
        # refs are uploaded bytes with an image name: never let a browser
        # sniff one into HTML
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                self.wfile.write(chunk)

    def read_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return None
        if length <= 0 or length > 200 * 1024 * 1024:
            return None
        self._body_read = True
        return self.rfile.read(length)

    def send_response(self, code, message=None):
        self._responded = True
        super().send_response(code, message)

    # ---- routing -------------------------------------------------------
    def do_GET(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        # one handler instance serves every request on a keep-alive connection
        self._responded = self._body_read = False
        try:
            why = request_refusal(self.headers, method)
            if why:
                self.send_error_json(403, why)
            else:
                self.route(method)
            if not self._body_read and self.headers.get("Content-Length", "0").strip() not in ("", "0"):
                # answered without reading the body (a refusal, a 404, a bad
                # name): its bytes would be parsed as the next request
                self.close_connection = True
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            # a readable 500 for the UI instead of a dropped connection; never
            # a second response on top of one that already started
            import traceback
            traceback.print_exc()
            self.close_connection = True
            if not self._responded:
                try:
                    self.send_error_json(500, f"server error: {e}")
                except OSError:
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

        # GET /api/setup — what's configured and what's ready, for the setup
        # banner and the kid flow's "needs a grown-up" message. Fast: no
        # Claude call (scripts/doctor.py --deep does the login check).
        if method == "GET" and parts == ["api", "setup"]:
            try:
                out = config.checks(config.get())
            except Exception as e:
                return self.send_error_json(500, f"setup checks failed: {e}")
            out["version"] = 1
            return self.send_json(out)

        # POST /api/server/restart — re-exec in place so code edits take effect
        # without hunting the PID (kill-style commands are awkward to automate).
        if method == "POST" and parts[:2] == ["api", "server"] \
                and len(parts) == 3 and parts[2] == "restart":
            self.send_json({"restarting": True})
            threading.Timer(0.4, lambda: os.execv(
                sys.executable, [sys.executable, os.path.abspath(__file__)]
                + sys.argv[1:])).start()
            return None

        # GET /api/library — the picture pool, each image with the list of
        # builds made from it (a picture can have a coin AND a toy).
        if method == "GET" and parts[:2] == ["api", "library"] and len(parts) == 2:
            root = projects_root()
            lib = os.path.join(root, "library")
            imgs = list_refs(lib)
            builds = {}    # image file -> [{project, kind, has_model}]
            for name in sorted(os.listdir(root)):
                pd = os.path.join(root, name)
                marker = os.path.join(pd, ".creation")
                if name == "library" or not os.path.isdir(pd) \
                        or not os.path.isfile(marker):
                    continue
                meta = creation_meta(pd)
                img, kind = meta.get("image"), meta.get("kind")
                has_model = bool(model_parts(pd)[0])
                if not meta and os.path.getsize(marker) != 0:
                    # hand-built project (a model designed by hand, not by a
                    # studio button): it belongs to every library picture it keeps a reference
                    # copy of. Association only — `protected` builds are never
                    # reused, redone, or overwritten by the studio.
                    for r in list_refs(pd):
                        builds.setdefault(r["file"], []).append({
                            "project": name,
                            "kind": detect_kind(pd) or "model",
                            "has_model": has_model,
                            "protected": True,
                        })
                    continue
                if not img:
                    # legacy auto-created project: exact by the image copy it
                    # holds, and only when one generated image identifies it.
                    gen = [r["file"] for r in list_refs(pd)
                           if r["file"].startswith("gen_")]
                    if len(gen) != 1:
                        continue
                    img = gen[0]
                builds.setdefault(img, []).append({
                    "project": name,
                    "kind": kind or detect_kind(pd) or "model",
                    "has_model": has_model,
                    "protected": False,
                })
            out = []
            for im in imgs:
                b = builds.get(im["file"], [])
                out.append({
                    "file": im["file"], "mtime": im["mtime"], "builds": b,
                    # `project`: first build with a model — older callers
                    "project": next((x["project"] for x in b if x["has_model"]), None),
                    "url": f"/api/projects/library/refs/{im['file']}"})
            return self.send_json({"images": out})

        # POST /api/library/archive {"image": "<file>"} — move a picture out
        # of the pool into projects/.archive/library_refs/ (reversible by hand).
        if method == "POST" and parts[:2] == ["api", "library"] \
                and len(parts) == 3 and parts[2] == "archive":
            try:
                image = os.path.basename(json.loads(self.read_body())["image"])
            except Exception:
                return self.send_error_json(400, 'body must be JSON: {"image": ...}')
            lib = os.path.join(projects_root(), "library")
            src = os.path.join(lib, "refs", image)
            if not safe_name(image) or not os.path.isfile(src):
                return self.send_error_json(404, f"library/refs/{image} does not exist")
            dest = unique_path(os.path.join(archive_dir(), "library_refs"), image)
            shutil.move(src, dest)
            # the Claude backend's vector original travels with its picture
            svg = os.path.join(lib, "vectors", os.path.splitext(image)[0] + ".svg")
            if os.path.isfile(svg):
                stem = os.path.splitext(os.path.basename(dest))[0]
                shutil.move(svg, unique_path(os.path.join(archive_dir(), "library_vectors"),
                                             stem + ".svg"))
            return self.send_json({"archived": api_path(dest)})

        if parts[0] != "api" or len(parts) < 2 or parts[1] != "projects":
            return self.send_error_json(404, "unknown route")

        # /api/projects
        if len(parts) == 2 and method == "GET":
            root = projects_root()
            os.makedirs(root, exist_ok=True)
            out = []
            for name in sorted(os.listdir(root)):
                pdir = os.path.join(root, name)
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
            pdir = os.path.join(projects_root(), name)
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
                env = config.envelope_mm(config.get())
                infos = []
                for r in model_parts(pdir)[0]:
                    i = dict(mesh_info(os.path.join(pdir, r)))   # copy: the cache is shared
                    if "bbox_mm" in i:
                        i["fits_bed"] = fits_envelope(i["bbox_mm"], env)
                    infos.append(i)
                combined = {}
                if infos and not any("error" in i for i in infos):
                    bbox = [max(i["bbox_mm"][k] for i in infos) for k in range(3)]
                    combined = {
                        "triangles": sum(i["triangles"] for i in infos),
                        "watertight": all(i["watertight"] for i in infos),
                        "fits_bed": all(i["fits_bed"] for i in infos),
                        "bbox_mm": bbox if len(infos) > 1 else infos[0]["bbox_mm"],
                    }
                return self.send_json({"parts": infos, "combined": combined,
                                       "envelope_mm": env})

            if sub == "refs" and len(parts) == 4:
                refs = [{**r, "url": f"/api/projects/{pname}/refs/{r['file']}"}
                        for r in list_refs(pdir)]
                return self.send_json({"refs": refs})

            if sub == "refs" and len(parts) == 5:
                if not safe_name(parts[4]):
                    return self.send_error_json(400, "bad name")
                return self.send_file(os.path.join(pdir, "refs", parts[4]))

            if sub == "files":
                cfg = config.get()
                return self.send_json({"files": list_files(pdir),
                                       "nano_key": bool(config.gemini_key(cfg)),
                                       "backend": config.resolve_backend(cfg)})

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
            return self.send_json({"path": api_path(path)})

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
            out = {"path": api_path(path)}
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
            out = {"path": api_path(path), "bytes": len(data)}
            if ext in MESH_EXTS:
                out.update(maybe_seed_live_model(pdir, path))
            return self.send_json(out)

        if sub == "slice":
            # a project's slice.json names its real print files (e.g. a K2 3MF with the
            # filaments already assigned); otherwise open the displayed model files
            sj = os.path.join(pdir, "slice.json")
            if os.path.isfile(sj):
                try:
                    with open(sj) as f:
                        spec = json.load(f)
                    assert isinstance(spec, dict)
                    opens = spec.get("open") or []
                    opens = [opens] if isinstance(opens, str) else list(opens)
                    assert all(isinstance(rel, str) for rel in opens)
                except Exception:
                    return self.send_error_json(
                        400, 'slice.json must be {"open": ["<file>", ...]} or {"message": ...}')
                if not opens:
                    return self.send_error_json(400, spec.get("message", "nothing to slice here"))
                paths, role = [os.path.normpath(os.path.join(pdir, rel)) for rel in opens], "slice.json"
                # siblings are fine (a display project pointing at its print
                # project's 3MF); anything outside the projects dir is not
                root = os.path.abspath(projects_root())
                if any(os.path.commonpath([os.path.abspath(p), root]) != root for p in paths):
                    return self.send_error_json(400, "slice.json points outside the projects folder")
            else:
                mp, role = model_parts(pdir)
                if not mp:
                    return self.send_error_json(400, "project has no model to slice")
                paths = [os.path.join(pdir, rel) for rel in mp]
            ok, msg = config.open_in_slicer(config.get(), paths)
            if not ok:
                return self.send_error_json(500, msg)
            return self.send_json({"opened": [api_path(p) for p in paths],
                                   "app": msg, "role": role})

        if sub == "generate":
            try:
                body = json.loads(self.read_body())
                subject = re.sub(r"\s+", " ", body["subject"]).strip()[:MAX_SUBJECT]
                assert subject
            except Exception:
                return self.send_error_json(400, 'body must be JSON: {"subject": ...}')
            cfg = config.get()
            provider = body.get("provider") or "auto"
            provider = imagegen.normalize_backend(provider) if isinstance(provider, str) else None
            if provider not in ("auto",) + imagegen.BACKENDS:
                return self.send_error_json(400, "provider must be auto|claude|comfyui|nano")
            backend = config.resolve_backend(cfg) if provider == "auto" else provider
            style = body.get("style") or "turnaround"
            if not isinstance(style, str) or style not in imagegen.STYLES:
                return self.send_error_json(400, "style must be " + "|".join(imagegen.STYLES))
            raw = body.get("count")
            try:
                # absent -> the configured number of options; given -> clamped
                count = int(raw if raw not in (None, "") else (cfg.get("options") or 4))
            except (TypeError, ValueError, OverflowError):     # JSON allows Infinity
                return self.send_error_json(400, "count must be a number")
            count = max(1, min(count, imagegen.MAX_OPTIONS))
            # not set up -> say so at once, so the UI shows "needs setup"
            # instead of a spinner that ends in a timeout
            ok, err, fix = imagegen.readiness(cfg, backend)
            if not ok:
                return self.send_json({"error": err, "setup": True, "fix": fix,
                                       "provider": backend}, 503)
            files, titles, used, errors = imagegen.generate(
                pdir, subject, backend, style, count, cfg)
            if not files:
                unique = list(dict.fromkeys(errors))
                if len(unique) == 1 and unique[0] in imagegen.SETUP_FIXES:
                    # every call hit the login wall / a rejected key: that's
                    # setup, not a glitch
                    return self.send_json({"error": unique[0], "setup": True,
                                           "fix": imagegen.SETUP_FIXES[unique[0]],
                                           "provider": used}, 503)
                return self.send_json({"error": "; ".join(unique) or "generation failed",
                                       "provider": used}, 502)
            return self.send_json({
                "provider": used, "errors": errors,
                "images": [{"file": f, "url": f"/api/projects/{pname}/refs/{f}", "title": t}
                           for f, t in zip(files, titles)],
                "reply": imagegen.reply_text(subject, len(files))})

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

            cfg = config.get()
            if not config.claude_bin(cfg):
                # before creation_project: a redo must not lose the old toy's
                # parts to a build that can't even start
                return self.send_error_json(409, CLAUDE_MISSING)
            target, tdir, dst = creation_project(src, image, "toy")
            # a Claude-drawn picture has its vector original: give the build a
            # copy in its own project — exact outlines and colour regions
            stem = os.path.splitext(image)[0] + ".svg"
            svg = None
            for cand in (os.path.join(pdir, "vectors", stem),
                         os.path.join(projects_root(), "library", "vectors", stem)):
                if os.path.isfile(cand):
                    svg = os.path.join(tdir, "vectors", stem)
                    if os.path.abspath(cand) != os.path.abspath(svg):
                        os.makedirs(os.path.dirname(svg), exist_ok=True)
                        shutil.copyfile(cand, svg)
                    break
            out = start_make3d(target, tdir, image, cfg, svg)
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
            target, tdir, dst = creation_project(src, image, "coin")
            # a redo: drop the old coin parts so a smaller retrace can't leave
            # stale colour regions behind
            pparts = os.path.join(tdir, "parts")
            if os.path.isdir(pparts):
                for f in os.listdir(pparts):
                    if f.startswith("coin_") and f.lower().endswith(".stl"):
                        os.remove(os.path.join(pparts, f))
            import subprocess
            try:
                r = subprocess.run(
                    [tool_python(), os.path.join(TOOLS, "make_coin.py"),
                     dst, "--name", target, "--out", tdir],
                    capture_output=True, text=True, timeout=120, cwd=REPO)
            except subprocess.TimeoutExpired:
                return self.send_error_json(500, "coin failed: the tracer took over 120 s")
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
            return self.send_json({"saved": cfg and api_path(cfg),
                                   "colors": current})

        if sub == "archive":
            # move the whole project into projects/.archive/ (reversible by
            # hand). Infrastructure projects are refused.
            if pname in ("library",):
                return self.send_error_json(
                    400, f"'{pname}' is infrastructure — not archivable")
            with _jobs_lock:
                j = _jobs.get(pname)
            if j and j["proc"].poll() is None:
                return self.send_error_json(409, "a build is running for this project")
            dest = unique_path(archive_dir(), pname)
            shutil.move(pdir, dest)
            return self.send_json({"archived": api_path(dest)})

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
            return self.send_json({"path": api_path(path)})

        return self.send_error_json(404, "unknown route")


def main():
    ap = argparse.ArgumentParser(description="3D Print Studio server")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--projects", default=None,
                    help="projects directory (default: projects_dir in studio.config.json, "
                         "else <repo>/projects); sets $STUDIO_PROJECTS_DIR")
    args = ap.parse_args()
    projects = args.projects or os.environ.get("STUDIO_PROJECTS_DIR", "").strip()
    if projects:
        # before the first config.get(): the environment layer wins over the file
        projects = os.path.abspath(os.path.expanduser(projects))
        os.environ["STUDIO_PROJECTS_DIR"] = projects
    # Run from the repo, whatever the caller's cwd: relative paths mean the repo, and a
    # bare-name dlopen (Pillow loads libfribidi that way) searches the cwd — from inside
    # ~/Documents that can block on a macOS privacy prompt and freeze every request.
    # The paths above are absolute first, and the restart re-exec gets them that way.
    sys.argv[1:] = ["--port", str(args.port)] + (["--projects", projects] if args.projects else [])
    if os.environ.get("STUDIO_CONFIG"):
        os.environ["STUDIO_CONFIG"] = config.CONFIG_PATH   # already absolute; the re-exec inherits it
    os.chdir(REPO)
    cfg = config.get()
    if cfg.get("_error"):
        print(f"warning: {cfg['_error']} — running on defaults", file=sys.stderr)
    root = projects_root(cfg)
    copied = seed_projects(root)
    try:
        # loopback only — never all interfaces
        httpd = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as e:
        sys.exit(f"Could not bind port {args.port} ({e}). Try --port <other>.")
    print(f"Studio: http://localhost:{args.port}/   projects: {root}"
          + (f"   seeded: {', '.join(copied)}" if copied else ""), flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
