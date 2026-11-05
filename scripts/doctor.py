#!/usr/bin/env python3
"""doctor.py — is 3D Print Studio set up? Stdlib only.

    scripts/doctor.py            human-readable check, ✅/❌ lines with fixes
    scripts/doctor.py --json     the same as JSON (config.checks() + a "doctor" block)
    scripts/doctor.py --deep     also make one tiny headless Claude call to prove the
                                 CLI is logged in (costs a few tokens; the desktop app
                                 being signed in is NOT enough for headless use)

Exit 0 when pictures, Make me 3D and coins are all ready; 1 otherwise. A missing
slicer is a warning, not a failure — you can open the files by hand.

Runs with any python3, before the venv exists (then the Python packages show as
missing and the fix is ./install.sh). When .venv exists and this was started
with some other python, it re-runs itself inside .venv — otherwise every package
would look missing just because the wrong interpreter was asked.
"""
import json
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV = os.path.join(REPO, ".venv")
VENV_PY = os.path.join(VENV, "bin", "python")


def venv_state():
    if os.path.exists(VENV_PY):
        return "ok"
    if os.path.lexists(VENV_PY) or os.path.isdir(VENV):
        return "broken"          # e.g. Homebrew upgraded Python and the symlink dangles
    return "missing"


def in_venv():
    try:
        return os.path.realpath(sys.prefix) == os.path.realpath(VENV)
    except OSError:
        return False


def maybe_reexec(argv):
    if "--no-venv" in argv or os.environ.get("STUDIO_DOCTOR_REEXEC") or in_venv():
        return
    if venv_state() != "ok":
        return
    os.environ["STUDIO_DOCTOR_REEXEC"] = "1"      # never loop
    try:
        os.execv(VENV_PY, [VENV_PY, os.path.abspath(__file__)] + argv)
    except OSError:
        pass                                      # fall through: report with this python


maybe_reexec(sys.argv[1:])

sys.path.insert(0, os.path.join(REPO, "studio"))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import config  # noqa: E402  (studio/config.py — the shared settings contract)
import configure  # noqa: E402  (its check() is the one rule book for config values)

_MISSING = object()


# ------------------------------------------------------------- output ----
def _can_emoji():
    try:
        "✅❌⚠️·×→".encode(sys.stdout.encoding or "ascii")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


EMOJI = _can_emoji()
OK, BAD, WARN, SKIP = (("✅", "❌", "⚠️ ", "➖") if EMOJI else ("[ok]", "[!!]", "[??]", "[--]"))
X = "×" if EMOJI else "x"
ARROW = "→" if EMOJI else "->"


def mark(v):
    return OK if v else (BAD if v is False else WARN)


def dims(v):
    return X.join(f"{float(n):g}" for n in v)


def py_version():
    return "%d.%d.%d" % sys.version_info[:3]


# ------------------------------------------------------------- report ----
def config_value_problems(cfg):
    """Hand edits in studio.config.json that the studio can't use. A value of
    the wrong type ("bed_mm": 260, "options": "four") made config.checks — and
    so this doctor and the studio's /api/setup — die with a traceback; it's put
    back to its default in `cfg` (so the rest of the report can run) and named
    here with its fix. Keys the studio doesn't know are a warning: a typo like
    kid.grownup is silently ignored, which looks like a bug in the studio."""
    if cfg.get("_error") or not cfg.get("_exists"):
        return []
    try:
        data = config.read_file(cfg["_path"])
    except ValueError:
        return []
    name = os.path.relpath(cfg["_path"], REPO) if cfg["_path"].startswith(REPO) else cfg["_path"]
    out = []

    def walk(d, prefix):
        for k, v in d.items():
            key = prefix + k
            default = config.get_path(config.DEFAULTS, key, _MISSING)
            if default is not _MISSING and isinstance(default, dict) and isinstance(v, dict):
                walk(v, key + ".")
                continue
            why = configure.check(key, v)
            if not why:
                continue
            if default is _MISSING:
                out.append({"what": f"{name}: {why} (the studio ignores it)",
                            "fix": f"rename it, or: scripts/configure.py unset {key}",
                            "optional": True})
                continue
            unusable = configure._kind(default) != configure._kind(v) or key == "printer.bed_mm"
            if unusable and config.get_path(cfg, key, _MISSING) == v:   # not overridden by env
                config.set_path(cfg, key, json.loads(json.dumps(default)))
            out.append({"what": f"{name}: {why}",
                        "fix": f"scripts/configure.py set {key} <value>   (or unset {key} for the default)"})
    walk(data, "")
    return out


def gather(deep):
    cfg = config.load()
    value_problems = config_value_problems(cfg)
    try:
        res = config.checks(cfg, deep=deep)
    except Exception as e:          # never a traceback from the setup check itself
        raise SystemExit(f"doctor.py: the setup checks crashed on this config ({type(e).__name__}: {e}).\n"
                         f"  look at it: scripts/configure.py show --file\n"
                         f"  or move {cfg.get('_path')} aside and re-run ./install.sh")
    state = venv_state()
    # config.load() sanitized the same bad values; config_value_problems already
    # named each one with its fix, so drop load()'s copy of those
    warned = set(cfg.get("_warnings") or [])
    problems = value_problems + [p for p in res["problems"] if p["what"] not in warned]
    if state != "ok":
        # Without the venv, "packages missing" and "resvg missing" are one problem
        # with one fix — say that, not three things that all mean "run install.sh".
        dep_words = ("Python packages missing", "resvg_py is not installed")
        problems = [p for p in problems if not p["what"].startswith(dep_words)]
        if state == "missing":
            problems.insert(0, {"what": "the studio's Python environment (.venv) doesn't exist yet",
                                "fix": "./install.sh"})
        else:
            problems.insert(0, {"what": ".venv is broken (its Python is gone — upgraded or moved?)",
                                "fix": "rm -rf .venv && ./install.sh"})
    elif in_venv() and sys.version_info < (3, 10):
        problems.insert(0, {"what": f".venv runs Python {py_version()}; the studio needs 3.10+",
                            "fix": "rm -rf .venv && ./install.sh"})
    res["problems"] = problems
    res["doctor"] = {
        "python": sys.executable,
        "python_version": py_version(),
        "venv": state,
        "in_venv": in_venv(),
        # a config that can't be read (or holds values it can't use) means the
        # studio runs on defaults, not on what was chosen — not "ready"
        "ok": bool(res["ready"]["pictures"] and res["ready"]["make3d"] and res["ready"]["coins"]
                   and not cfg.get("_error")
                   and not any(not p.get("optional") for p in value_problems)),
    }
    return res


def pictures_line(r):
    b = r["resolved_backend"]
    auto = " (auto)" if (r.get("image_backend") or "auto") == "auto" else ""
    if b == "claude":
        if not r["claude"]["found"]:
            detail = "Claude Code draws them — but the claude CLI isn't installed"
        else:
            detail = f"Claude Code draws them ({r['claude']['draw_model']})"
    elif b == "comfyui":
        c = r["comfyui"]
        if not c["reachable"]:
            detail = f"ComfyUI isn't answering ({c['configured_url'] or 'ports 8188/8000/8189'})"
        elif c["missing_models"]:
            detail = f"ComfyUI at {c['url']} is missing {len(c['missing_models'])} model(s)"
        else:
            detail = f"ComfyUI at {c['url']} (Z-Image Turbo)"
    else:
        n = r["nano"]
        detail = f"Nano Banana ({n['model']})" + ("" if n["key"] else " — no Gemini API key")
    return f"{b}{auto}, {r['options']} per ask — {detail}"


def print_human(r):
    d = r["doctor"]
    out = []
    out.append("3D Print Studio — setup check")
    cfg_note = r["config_file"] if r["configured"] else f"{r['config_file']} (not written yet — run ./install.sh)"
    out.append(f"   config     {cfg_note}")
    out.append(f"{mark(r['ready']['pictures'])} pictures   {pictures_line(r)}")
    cl = r["claude"]
    if cl["found"]:
        out.append(f"{mark(r['ready']['make3d'])} make 3D    Claude Code at {cl['path']} ({cl['build_model']})")
    else:
        out.append(f"{BAD} make 3D    the Claude Code CLI isn't installed")
    if cl["login"] is True:
        out.append(f"{OK} login      the CLI answers headless calls")
    elif cl["login"] is False:
        out.append(f"{BAD} login      {cl['login_detail']}")
    elif cl["found"]:
        out.append(f"{WARN} login      not checked — scripts/doctor.py --deep makes one tiny Claude call")
    out.append(f"{mark(r['ready']['coins'])} coins      "
               + ("the coin tracer's packages are there" if r["ready"]["coins"]
                  else "opencv / trimesh / shapely missing"))
    sl = r["slicer"]
    sl_mark = OK if sl["found"] else (WARN if sl["found"] is False else SKIP)
    sl_note = ("found" if sl["found"] else
               "not found (optional — you can open the files by hand)" if sl["found"] is False
               else "can't tell on this OS")
    out.append(f"{sl_mark} slicer     {sl['name']} — {sl_note}")
    venv_note = {"ok": ".venv", "missing": "no .venv yet", "broken": ".venv is broken"}[d["venv"]]
    deps_ok = all(r["python_deps"].values())
    out.append(f"{OK if deps_ok else BAD} python     {venv_note}; running {d['python_version']}"
               + ("" if deps_ok else "; missing " + ", ".join(m for m, ok in r["python_deps"].items() if not ok)))
    p = r["printer"]
    out.append(f"   printer    {p['name']} · bed {dims(p['bed_mm'])} mm · design envelope {dims(p['envelope_mm'])} mm")
    k = r["kid"]
    out.append(f"   kid mode   calls the helper \"{k['grown_up']}\", toys for ages {k['ages']}")

    probs = r["problems"]
    if probs:
        out.append("")
        out.append(f"{len(probs)} thing{'s' if len(probs) != 1 else ''} to fix:")
        for pr in probs:
            # a missing slicer never blocks anything (files open by hand) — warn, don't fail
            optional = pr.get("optional") or (pr["what"].startswith("slicer ") and sl["found"] is False)
            out.append(f"  {WARN if optional else BAD} {pr['what']}")
            out.append(f"     {ARROW} {pr['fix']}")
    out.append("")
    if d["ok"]:
        tail = "Ready: pictures, coins and Make me 3D all work."
        if cl["login"] is None and cl["found"]:
            tail += " (Run with --deep once to prove the Claude CLI is logged in.)"
        out.append(tail)
    elif r["ready"]["pictures"] and r["ready"]["make3d"] and r["ready"]["coins"]:
        out.append("Works, but on defaults where the config couldn't be used — fix the config items above.")
    else:
        out.append("Not ready yet — fix the items above, then run scripts/doctor.py again.")
    text = "\n".join(out)
    if not EMOJI:          # a C/ASCII terminal: plain punctuation, never a crash
        for a, b in (("—", "-"), ("·", "|"), ("…", "..."), ("³", "^3"), ("→", "->"), ("×", "x")):
            text = text.replace(a, b)
        enc = sys.stdout.encoding or "ascii"
        text = text.encode(enc, errors="replace").decode(enc)
    print(text)


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(__doc__.strip())
        return 0
    unknown = [a for a in argv if a not in ("--json", "--deep", "--no-venv")]
    if unknown:
        print(f"doctor.py: unknown option {unknown[0]} (try --help)", file=sys.stderr)
        return 2
    r = gather(deep="--deep" in argv)
    if "--json" in argv:
        print(json.dumps(r, indent=2))
    else:
        print_human(r)
    return 0 if r["doctor"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
