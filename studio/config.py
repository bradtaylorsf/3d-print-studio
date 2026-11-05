#!/usr/bin/env python3
"""config.py — the studio's settings and setup checks. Stdlib only.

One JSON file, `studio.config.json` at the repo root (gitignored, written by
install.sh / scripts/configure.py), layered over DEFAULTS, with environment
variables on top:

    defaults  <  studio.config.json  <  environment

Used by studio/server.py (reloaded whenever the file changes, so re-running
install.sh never needs a server restart), scripts/doctor.py and
scripts/configure.py. Keep this module importable with no third-party
packages — doctor.py runs it before the venv exists.

The keys (see studio.config.example.json):

    image_backend   "claude" | "comfyui" | "nano" | "auto" — who draws the pictures
    options         pictures per ask (4)
    projects_dir    "" = <repo>/projects
    claude.*        the user's own Claude Code CLI, run headless
    comfyui.*       a local ComfyUI running Z-Image Turbo
    nano.*          Google Nano Banana (needs a Gemini API key)
    printer.*       build volume + the slicer the 🖨 button opens
    kid.*           what kid mode calls the helping adult, and who the toys are for
"""
import copy
import json
import math
import os
import shutil
import subprocess
import sys
import threading
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.abspath(os.path.expanduser(
    os.environ.get("STUDIO_CONFIG") or os.path.join(REPO, "studio.config.json")))

BACKENDS = ("claude", "comfyui", "nano")
COMFY_PROBE_PORTS = (8188, 8000, 8189)   # ComfyUI's default first; a hand-started one is often on 8000
LEGACY_GEMINI_KEY_FILE = "~/.config/3d-prints/gemini_key"

DEFAULTS = {
    "image_backend": "auto",
    "options": 4,
    "projects_dir": "",
    "claude": {
        "bin": "",                          # "" = $STUDIO_CLAUDE_BIN, PATH, then the desktop app's copy
        "draw_model": "claude-opus-5-5",    # draws the pictures when image_backend is "claude"
        "build_model": "claude-opus-5-5",   # builds the 3D model ("Make me 3D")
        "build_timeout_min": 30,            # Opus builds run 5–20 min; past this it is wedged
    },
    "comfyui": {
        "url": "",                          # "" = probe 127.0.0.1 on COMFY_PROBE_PORTS
        "workspace": "",                    # set by scripts/setup_comfyui.sh; lets start.sh launch it
        "unet": "z_image_turbo_bf16.safetensors",
        "clip": "qwen_3_4b.safetensors",
        "vae": "z_image_ae.safetensors",    # upstream ae.safetensors is accepted too
        "steps": 8,
    },
    "nano": {
        "model": "gemini-2.5-flash-image",
        "key_file": "~/.config/3d-print-studio/gemini_key",
    },
    "printer": {
        "name": "Creality K2",
        "bed_mm": [260, 260, 260],
        "margin_mm": 5,                     # design envelope = bed - margin (255³ on a K2)
        "slicer": "Creality Print",         # macOS app name, or a command / path on Linux
    },
    "kid": {
        "grown_up": "a grown-up",           # "Go get a grown-up to help you from here."
        "ages": "5 to 9",                   # shapes how chunky and robust the toys are
    },
}

# environment variable -> dotted config key (and a type to coerce to)
ENV_OVERRIDES = {
    "STUDIO_IMAGE_BACKEND": ("image_backend", str),
    "STUDIO_OPTIONS": ("options", int),
    "STUDIO_PROJECTS_DIR": ("projects_dir", str),
    "STUDIO_CLAUDE_BIN": ("claude.bin", str),
    "STUDIO_DRAW_MODEL": ("claude.draw_model", str),
    "STUDIO_MAKE3D_MODEL": ("claude.build_model", str),
    "STUDIO_COMFYUI_URL": ("comfyui.url", str),
    "STUDIO_NANO_MODEL": ("nano.model", str),
    "STUDIO_SLICER_APP": ("printer.slicer", str),
    "STUDIO_GROWN_UP": ("kid.grown_up", str),
}


# --------------------------------------------------------------- loading --
def _merge(base, over):
    """Deep merge `over` into a copy of `base`. Dicts merge; anything else replaces."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def get_path(cfg, dotted, default=None):
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def set_path(cfg, dotted, value):
    """Set cfg["a"]["b"] for "a.b", creating dicts on the way."""
    parts = dotted.split(".")
    cur = cfg
    for part in parts[:-1]:
        if not isinstance(cur.get(part), dict):
            cur[part] = {}
        cur = cur[part]
    cur[parts[-1]] = value
    return cfg


def read_file(path=None):
    """The raw file contents ({} if missing). Raises ValueError on bad JSON —
    a typo in the config should be loud, not silently ignored."""
    path = path or CONFIG_PATH
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{path} must hold a JSON object")
    return data


def _kind(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        # json.load takes NaN/Infinity, and json.dumps writes them back out as
        # non-JSON the browser can't parse — so they aren't numbers here
        return "number" if math.isfinite(v) else "other"
    return {str: "string", list: "list", dict: "object"}.get(type(v), "other")


def _sanitize(cfg, defaults=DEFAULTS, prefix="", name="studio.config.json"):
    """Put the default back for any hand-edited value of the wrong JSON kind
    ("options": "four", "printer": {"bed_mm": 260}) — the server reads these
    on every request and a TypeError there is a 500, not a helpful message.
    Returns the list of warnings."""
    warnings = []
    for k, dv in defaults.items():
        key = prefix + k
        if k not in cfg:
            continue
        v = cfg[k]
        if isinstance(dv, dict):
            if isinstance(v, dict):
                warnings += _sanitize(v, dv, key + ".", name)
                continue
        elif _kind(v) == _kind(dv):
            if key == "printer.bed_mm" and not (
                    len(v) == 3 and all(_kind(x) == "number" and x > 0 for x in v)):
                pass
            elif _kind(v) == "number" and v < 0:
                pass
            else:
                continue
        want = ("three positive numbers" if key == "printer.bed_mm"
                else f"a {_kind(dv)}" + (" of 0 or more" if _kind(dv) == "number" else ""))
        warnings.append(f"{name}: {key} = {json.dumps(v)} is not valid "
                        f"(expected {want}) — using the default {json.dumps(dv)}")
        cfg[k] = copy.deepcopy(dv)
    return warnings


def load(path=None):
    """defaults < file < environment. Adds "_path", "_exists", "_error"
    (a bad file falls back to defaults and reports why, so the studio still starts)
    and "_warnings" (wrong-typed values that were replaced by their defaults)."""
    path = path or CONFIG_PATH
    error = None
    try:
        data = read_file(path)
    except ValueError as e:
        data, error = {}, str(e)
    cfg = _merge(DEFAULTS, data)
    warnings = _sanitize(cfg, name=os.path.basename(path))
    for env, (key, typ) in ENV_OVERRIDES.items():
        raw = os.environ.get(env, "").strip()
        if raw:
            try:
                set_path(cfg, key, typ(raw))
            except ValueError:
                pass
    cfg["_path"] = path
    cfg["_exists"] = os.path.isfile(path)
    cfg["_error"] = error
    cfg["_warnings"] = warnings
    return cfg


_cache = {"mtime": None, "cfg": None}
_cache_lock = threading.Lock()


def get():
    """load(), cached until the file's mtime changes."""
    try:
        mtime = os.path.getmtime(CONFIG_PATH)
    except OSError:
        mtime = None
    with _cache_lock:
        if _cache["cfg"] is None or _cache["mtime"] != mtime:
            _cache["cfg"], _cache["mtime"] = load(), mtime
        return _cache["cfg"]


def save(updates, path=None):
    """Deep-merge `updates` into the FILE (never the environment layer) and
    write it atomically. Returns the new file contents."""
    path = path or CONFIG_PATH
    data = _merge(read_file(path), updates)
    for k in [k for k in data if k.startswith("_")]:
        data.pop(k)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return data


# ------------------------------------------------------------ derived ----
def projects_dir(cfg):
    d = (cfg.get("projects_dir") or "").strip()
    return os.path.abspath(os.path.expanduser(d)) if d else os.path.join(REPO, "projects")


def bed_mm(cfg):
    bed = get_path(cfg, "printer.bed_mm") or DEFAULTS["printer"]["bed_mm"]
    return [float(v) for v in bed][:3]


def envelope_mm(cfg):
    """The design envelope: the bed minus the margin on every axis."""
    m = float(get_path(cfg, "printer.margin_mm", 5) or 0)
    return [max(v - m, 1.0) for v in bed_mm(cfg)]


def claude_bin(cfg):
    """Resolve the user's claude CLI: config, $STUDIO_CLAUDE_BIN (already folded
    into config), PATH, the usual install locations, then the Claude desktop
    app's bundled copy — a machine that runs Claude Code only through the
    desktop app has no `claude` on PATH at all."""
    import glob
    explicit = (get_path(cfg, "claude.bin") or "").strip()
    if explicit:
        p = os.path.expanduser(explicit)
        return p if os.path.isfile(p) or shutil.which(p) else None
    found = shutil.which("claude")
    if found:
        return found
    for p in ("~/.local/bin/claude", "~/.claude/local/claude", "/opt/homebrew/bin/claude",
              "/usr/local/bin/claude"):
        p = os.path.expanduser(p)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    cands = glob.glob(os.path.expanduser(
        "~/Library/Application Support/Claude/claude-code/*/claude.app/Contents/MacOS/claude"))
    return max(cands, key=os.path.getmtime) if cands else None


def gemini_key(cfg):
    for env in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        k = os.environ.get(env, "").strip()
        if k:
            return k
    for f in (get_path(cfg, "nano.key_file") or "", LEGACY_GEMINI_KEY_FILE):
        if not f:
            continue
        try:
            with open(os.path.expanduser(f), encoding="utf-8") as fh:
                k = fh.read().strip()
            if k:
                return k
        except OSError:
            continue
    return ""


# -------------------------------------------------------------- ComfyUI --
_probe_cache = {}          # url -> (time, ok)
_PROBE_TTL = 10.0


def _http_json(url, timeout=3):
    import urllib.request
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def comfy_alive(url):
    """Does a ComfyUI answer at url? Cached for a few seconds — the studio
    asks on every setup poll and a dead port costs a full timeout."""
    now = time.time()
    hit = _probe_cache.get(url)
    if hit and now - hit[0] < _PROBE_TTL:
        return hit[1]
    try:
        _http_json(url.rstrip("/") + "/system_stats", timeout=2)
        ok = True
    except Exception:
        ok = False
    _probe_cache[url] = (now, ok)
    return ok


def comfy_url(cfg):
    """The ComfyUI to use: the configured url if it answers, else the first
    local port that does. None when nothing answers."""
    configured = (get_path(cfg, "comfyui.url") or "").strip().rstrip("/")
    if configured and "://" not in configured:
        configured = "http://" + configured       # a hand-typed "localhost:8188"
    if configured:
        return configured if comfy_alive(configured) else None
    for port in COMFY_PROBE_PORTS:
        url = f"http://127.0.0.1:{port}"
        if comfy_alive(url):
            return url
    return None


def comfy_models(url):
    """{"diffusion_models": [...], "text_encoders": [...], "vae": [...]} as the
    running ComfyUI sees them, or None if it can't be asked."""
    out = {}
    try:
        for folder in ("diffusion_models", "unet", "text_encoders", "clip", "vae"):
            try:
                out[folder] = _http_json(f"{url}/models/{folder}", timeout=4)
            except Exception:
                out[folder] = []
    except Exception:
        return None
    return out


def comfy_model_choice(cfg, url):
    """The (unet, clip, vae) filenames to put in the workflow, and the list of
    required files ComfyUI doesn't have. The VAE falls back to upstream's
    `ae.safetensors` name when the renamed one isn't there."""
    want = {
        "unet": get_path(cfg, "comfyui.unet"),
        "clip": get_path(cfg, "comfyui.clip"),
        "vae": get_path(cfg, "comfyui.vae"),
    }
    models = comfy_models(url) if url else None
    if models is None:
        return want, []
    have_unet = set(models.get("diffusion_models", [])) | set(models.get("unet", []))
    have_clip = set(models.get("text_encoders", [])) | set(models.get("clip", []))
    have_vae = set(models.get("vae", []))
    missing = []
    if want["unet"] not in have_unet:
        missing.append(f"diffusion_models/{want['unet']}")
    if want["clip"] not in have_clip:
        missing.append(f"text_encoders/{want['clip']}")
    if want["vae"] not in have_vae:
        if "ae.safetensors" in have_vae:
            want["vae"] = "ae.safetensors"
        else:
            missing.append(f"vae/{want['vae']}")
    return want, missing


# ------------------------------------------------------------- backend --
def resolve_backend(cfg):
    """The backend that will actually draw. "auto" picks, in order: Nano Banana
    if a key exists, a running ComfyUI, else Claude."""
    b = (cfg.get("image_backend") or "auto").strip().lower()
    if b == "comfy":
        b = "comfyui"
    if b in BACKENDS:
        return b
    if gemini_key(cfg):
        return "nano"
    if comfy_url(cfg):
        return "comfyui"
    return "claude"


def resvg_ok():
    import importlib.util
    return importlib.util.find_spec("resvg_py") is not None


# -------------------------------------------------------------- slicer --
def slicer_found(cfg):
    """True / False when we can tell, None when we can't (e.g. Windows)."""
    name = (get_path(cfg, "printer.slicer") or "").strip()
    if not name:
        return False
    if sys.platform == "darwin":
        if name.startswith("/"):
            return os.path.exists(name)
        app = name if name.endswith(".app") else name + ".app"
        return any(os.path.isdir(os.path.join(d, app))
                   for d in ("/Applications", os.path.expanduser("~/Applications")))
    if sys.platform.startswith("linux"):
        if "/" in name:
            return os.path.exists(os.path.expanduser(name))
        return bool(shutil.which(name) or shutil.which(name.lower().replace(" ", "-")))
    return None


def open_in_slicer(cfg, paths):
    """Open model files in the configured slicer. Returns (ok, message)."""
    name = (get_path(cfg, "printer.slicer") or "").strip()
    try:
        if sys.platform == "darwin":
            r = subprocess.run(["open", "-a", name, *paths],
                               capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                return False, f"'{name}' failed to open: {r.stderr.strip() or 'is it installed?'}"
            return True, name
        if sys.platform.startswith("linux"):
            cmd = os.path.expanduser(name) if "/" in name else (
                shutil.which(name) or shutil.which(name.lower().replace(" ", "-")))
            if cmd:
                subprocess.Popen([cmd, *paths], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True, name
            for p in paths:                 # no slicer command: the desktop's default app
                subprocess.Popen(["xdg-open", p], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True, "xdg-open"
        if sys.platform.startswith("win"):
            for p in paths:
                os.startfile(p)             # noqa: the file association picks the slicer
            return True, "default app"
    except Exception as e:
        return False, f"could not launch slicer: {e}"
    return False, f"don't know how to open a slicer on {sys.platform}"


# --------------------------------------------------------------- login --
def claude_login_check(cfg, timeout=90):
    """A real one-turn headless call — the only reliable test that the CLI is
    logged in for headless use (the desktop app being signed in is NOT enough).
    Returns (ok, detail). Costs a few tokens; doctor runs it only with --deep."""
    import tempfile
    binpath = claude_bin(cfg)
    if not binpath:
        return False, "claude CLI not found"
    with tempfile.TemporaryDirectory() as tmp:
        try:
            r = subprocess.run(
                [binpath, "-p", "Reply with the single word OK.", "--model", "haiku",
                 "--output-format", "json", "--strict-mcp-config", "--tools", "",
                 "--no-session-persistence"],
                cwd=tmp, capture_output=True, text=True, timeout=timeout,
                stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return False, f"no answer in {timeout}s"
        except OSError as e:
            return False, f"could not run {binpath}: {e}"
    out = (r.stdout or "") + (r.stderr or "")
    low = out.lower()
    if r.returncode == 0 and '"is_error":false' in out.replace(" ", ""):
        return True, "logged in"
    if "not logged in" in low or "/login" in low or "authenticat" in low or "api key" in low:
        return False, "not logged in for headless use — run `claude`, then /login"
    return False, (out.strip().splitlines() or [f"exit {r.returncode}"])[-1][:200]


# --------------------------------------------------------------- checks --
def _display_path(path):
    """Repo-relative inside the repo; a STUDIO_CONFIG elsewhere stays absolute
    rather than a ../../../ climb."""
    rel = os.path.relpath(path, REPO)
    return path if rel.startswith("..") else rel


def checks(cfg, deep=False):
    """Everything the setup banner (/api/setup) and scripts/doctor.py report.
    Fast by default; deep=True adds the real Claude login call."""
    import importlib.util
    backend = resolve_backend(cfg)
    binpath = claude_bin(cfg)
    url = comfy_url(cfg)
    _, missing = comfy_model_choice(cfg, url) if url else ({}, [])
    key = bool(gemini_key(cfg))
    resvg = resvg_ok()
    slicer = slicer_found(cfg)
    deps = {m: importlib.util.find_spec(m) is not None
            for m in ("trimesh", "manifold3d", "numpy", "shapely", "cv2", "skimage", "resvg_py")}

    login, login_detail = (None, "not checked (doctor --deep checks it)")
    if deep:
        login, login_detail = claude_login_check(cfg)

    problems = []
    if cfg.get("_error"):
        problems.append({"what": cfg["_error"], "fix": "fix the JSON, or re-run ./install.sh"})
    for w in cfg.get("_warnings") or []:
        problems.append({"what": w, "fix": "scripts/configure.py set <key> <value>, or unset <key> for the default"})
    if not binpath:
        problems.append({"what": "Claude Code CLI not found (needed for Make me 3D"
                                 + (" and for drawing" if backend == "claude" else "") + ")",
                         "fix": "install it: curl -fsSL https://claude.ai/install.sh | bash — "
                                "then run `claude` once and /login"})
    elif login is False:
        problems.append({"what": f"Claude Code CLI: {login_detail}",
                         "fix": "run `claude` in a terminal, then /login"})
    if backend == "comfyui":
        if not url:
            where = get_path(cfg, "comfyui.url") or "ports " + "/".join(map(str, COMFY_PROBE_PORTS))
            problems.append({"what": f"ComfyUI is not answering ({where})",
                             "fix": "start it (./start.sh launches it when comfyui.workspace is set), "
                                    "or run scripts/setup_comfyui.sh"})
        elif missing:
            problems.append({"what": "ComfyUI is missing models: " + ", ".join(missing),
                             "fix": "run scripts/setup_comfyui.sh --models-only"})
    if backend == "nano" and not key:
        problems.append({"what": "no Gemini API key for Nano Banana",
                         "fix": "set GEMINI_API_KEY, or put the key in "
                                + get_path(cfg, "nano.key_file", DEFAULTS["nano"]["key_file"])})
    if backend == "claude" and not resvg:
        problems.append({"what": "resvg_py is not installed (turns Claude's drawings into PNGs)",
                         "fix": ".venv/bin/pip install -r requirements.txt"})
    missing_deps = [m for m, ok in deps.items() if not ok]
    if missing_deps:
        problems.append({"what": "Python packages missing: " + ", ".join(missing_deps),
                         "fix": "./install.sh (or .venv/bin/pip install -r requirements.txt)"})
    if slicer is False:
        problems.append({"what": f"slicer '{get_path(cfg, 'printer.slicer')}' not found",
                         "fix": "install it, or set printer.slicer in studio.config.json"})

    pictures_ready = {
        "claude": bool(binpath) and resvg and login is not False,
        "comfyui": bool(url) and not missing,
        "nano": key,
    }[backend]
    return {
        "config_file": _display_path(cfg.get("_path") or CONFIG_PATH),
        "configured": bool(cfg.get("_exists")),
        "image_backend": cfg.get("image_backend"),
        "resolved_backend": backend,
        "options": int(cfg.get("options") or 4),
        "ready": {
            "pictures": pictures_ready,
            "make3d": bool(binpath) and login is not False,
            "coins": deps["cv2"] and deps["trimesh"] and deps["shapely"],
            "slicer": slicer,
        },
        "claude": {"found": bool(binpath), "path": binpath,
                   "draw_model": get_path(cfg, "claude.draw_model"),
                   "build_model": get_path(cfg, "claude.build_model"),
                   "login": login, "login_detail": login_detail},
        "comfyui": {"url": url, "configured_url": get_path(cfg, "comfyui.url") or None,
                    "reachable": bool(url), "missing_models": missing},
        "nano": {"key": key, "model": get_path(cfg, "nano.model")},
        "resvg": resvg,
        "python_deps": deps,
        "printer": {"name": get_path(cfg, "printer.name"), "bed_mm": bed_mm(cfg),
                    "envelope_mm": envelope_mm(cfg), "slicer": get_path(cfg, "printer.slicer")},
        "slicer": {"name": get_path(cfg, "printer.slicer"), "found": slicer},
        "kid": {"grown_up": get_path(cfg, "kid.grown_up"), "ages": get_path(cfg, "kid.ages")},
        "problems": problems,
    }


if __name__ == "__main__":
    print(json.dumps(checks(load(), deep="--deep" in sys.argv), indent=2))
