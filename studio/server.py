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
