#!/usr/bin/env python3
"""smoke_test.py — start the studio against a throwaway projects folder and
poke every core endpoint. Stdlib only. Spends nothing: the picture backend is
set to Nano Banana with no key (and HOME points at an empty temp folder, so no
key file on this machine can be found), so "generate" must answer 503
"needs setup" without calling anyone.

    python3 scripts/smoke_test.py [--port 8790] [--keep]

Uses .venv/bin/python for the server when it exists (the coin check needs the
mesh libraries). Exit 0 when every check passes, 1 otherwise.
"""
import argparse
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(REPO, "studio", "server.py")


# ------------------------------------------------------------------ bits --
def tiny_png(size=256):
    """A sticker-ish test picture: white background, a red disc, a light-blue
    square and a yellow dot — three flat colours the coin tracer can split."""
    c = size / 2
    rows = []
    for y in range(size):
        row = bytearray([0])                       # filter: none
        for x in range(size):
            px = (255, 255, 255)
            if (x - c) ** 2 + (y - c) ** 2 <= (size * 0.36) ** 2:
                px = (220, 40, 40)
            if abs(x - c) <= size * 0.14 and abs(y - c) <= size * 0.14:
                px = (80, 140, 255)
            if (x - c) ** 2 + (y - c * 0.55) ** 2 <= (size * 0.07) ** 2:
                px = (250, 210, 40)
            row += bytes(px)
        rows.append(bytes(row))

    def chunk(kind, data):
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
            + chunk(b"IEND", b""))


def free_port(start, end=8799):
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return None


class Client:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"

    def call(self, method, path, body=None, raw=None, timeout=60, headers=None):
        """(status, parsed JSON or raw bytes)."""
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status, blob, ctype = r.status, r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            status, blob, ctype = e.code, e.read(), e.headers.get("Content-Type", "")
        if "json" in ctype:
            try:
                return status, json.loads(blob)
            except ValueError:
                pass
        return status, blob


# ----------------------------------------------------------------- checks --
class Checks:
    def __init__(self):
        self.passed, self.failed = 0, []

    def __call__(self, name, ok, detail=""):
        if ok:
            self.passed += 1
            print(f"  ok    {name}")
        else:
            self.failed.append(name)
            print(f"  FAIL  {name}" + (f"  — {detail}" if detail else ""))
        return bool(ok)


def short(obj, n=300):
    s = obj if isinstance(obj, str) else json.dumps(obj) if not isinstance(obj, bytes) else repr(obj[:120])
    return s[:n]


def run_checks(c, check):
    # the page
    st, body = c.call("GET", "/")
    check("GET / serves the viewer", st == 200 and isinstance(body, bytes)
          and b"<html" in body.lower(), f"status {st}")

    # setup payload — the contract the UI and doctor.py read
    st, setup = c.call("GET", "/api/setup")
    ok = st == 200 and isinstance(setup, dict)
    check("GET /api/setup answers", ok, f"status {st} {short(setup)}")
    if ok:
        need = ["version", "config_file", "configured", "image_backend", "resolved_backend",
                "options", "ready", "claude", "comfyui", "nano", "resvg", "python_deps",
                "printer", "slicer", "kid", "problems"]
        missing = [k for k in need if k not in setup]
        check("setup has every top-level key", not missing, f"missing {missing}")
        check("setup version is 1", setup.get("version") == 1)
        check("setup reads the temp config (nano, 4 options)",
              setup.get("image_backend") == "nano" and setup.get("resolved_backend") == "nano"
              and setup.get("options") == 4 and setup.get("configured") is True,
              short({k: setup.get(k) for k in ("image_backend", "resolved_backend",
                                               "options", "configured")}))
        ready = setup.get("ready") or {}
        check("setup.ready has pictures/make3d/coins/slicer",
              all(k in ready for k in ("pictures", "make3d", "coins", "slicer")), short(ready))
        pr = setup.get("printer") or {}
        check("setup.printer has bed + envelope",
              len(pr.get("bed_mm") or []) == 3 and len(pr.get("envelope_mm") or []) == 3
              and bool(pr.get("name")), short(pr))
        kid = setup.get("kid") or {}
        check("setup.kid has grown_up + ages", bool(kid.get("grown_up")) and bool(kid.get("ages")),
              short(kid))
        check("setup.problems is a list of {what, fix}",
              isinstance(setup.get("problems"), list)
              and all({"what", "fix"} <= set(p) for p in setup["problems"]))
        check("no Gemini key is visible (so generate can't spend)",
              (setup.get("nano") or {}).get("key") is False, short(setup.get("nano")))

    # projects + first-run seeding
    st, j = c.call("GET", "/api/projects")
    names = [p.get("name") for p in (j.get("projects") or [])] if isinstance(j, dict) else []
    check("GET /api/projects lists projects", st == 200 and isinstance(j, dict)
          and isinstance(j.get("projects"), list), f"status {st} {short(j)}")
    examples = os.path.join(REPO, "examples")
    if os.path.isdir(examples):
        want = sorted(n for n in os.listdir(examples)
                      if os.path.isdir(os.path.join(examples, n)) and not n.startswith("."))
        check("first start seeded examples/ into the empty projects dir",
              all(n in names for n in want), f"want {want}, have {names}")
    else:
        print("  skip  seeding (no examples/ folder yet)")
    check("the picture library exists", "library" in names, short(names))

    st, j = c.call("POST", "/api/projects", {"name": "Smoke Test"})
    check("POST /api/projects creates a project", st == 200 and isinstance(j, dict)
          and j.get("name") == "smoke_test" and j.get("created") is True, f"status {st} {short(j)}")

    st, j = c.call("POST", "/api/projects/smoke_test/refs?name=dot.png", raw=tiny_png())
    path = j.get("path", "") if isinstance(j, dict) else ""
    check("POST refs uploads a PNG", st == 200 and path.endswith("smoke_test/refs/dot.png"),
          f"status {st} {short(j)}")
    check("response paths are never absolute or ../", path and not path.startswith(("/", "..")),
          path)
    st, j = c.call("GET", "/api/projects/smoke_test/refs")
    check("GET refs lists it", st == 200 and isinstance(j, dict)
          and any(r.get("file") == "dot.png" for r in j.get("refs", [])), short(j))

    # coin: the deterministic tracer, no AI
    st, j = c.call("POST", "/api/projects/smoke_test/coin", {"image": "dot.png"}, timeout=180)
    coin = j.get("project") if isinstance(j, dict) else None
    check("POST coin traces the picture into a new project", st == 200 and coin == "dot_coin",
          f"status {st} {short(j)}")
    if coin:
        st, m = c.call("GET", f"/api/projects/{coin}/manifest")
        files = [p.get("file") for p in (m.get("parts") or [])] if isinstance(m, dict) else []
        check("coin has a body + colour parts",
              "parts/coin_body.stl" in files and any(f.startswith("parts/coin_c") for f in files),
              short(files))
        st, info = c.call("GET", f"/api/projects/{coin}/info", timeout=120)
        comb = info.get("combined", {}) if isinstance(info, dict) else {}
        check("GET info reports fits_bed", st == 200 and isinstance(comb.get("fits_bed"), bool)
              and all(isinstance(p.get("fits_bed"), bool) for p in info.get("parts", [])),
              f"status {st} {short(info)}")
        check("the 28 mm coin fits the bed and is watertight",
              comb.get("fits_bed") is True and comb.get("watertight") is True, short(comb))
        st, blob = c.call("GET", f"/api/projects/{coin}/model/coin_body.stl")
        check("GET model serves STL bytes", st == 200 and isinstance(blob, bytes) and len(blob) > 84,
              f"status {st}")
        st, j = c.call("GET", f"/api/projects/{coin}/files")
        check("GET files names the picture backend", st == 200 and isinstance(j, dict)
              and j.get("backend") == "nano" and j.get("nano_key") is False, short(j))
        st, j = c.call("POST", "/api/projects/smoke_test/coin", {"image": "dot.png"}, timeout=180)
        check("coin again = redo in the same project",
              st == 200 and isinstance(j, dict) and j.get("project") == coin, short(j))

    st, j = c.call("GET", "/api/library")
    check("GET /api/library answers", st == 200 and isinstance(j, dict)
          and isinstance(j.get("images"), list), f"status {st} {short(j)}")
    st, j = c.call("POST", "/api/projects/library/archive")
    check("the library refuses to be archived", st == 400, f"status {st} {short(j)}")
    st, j = c.call("GET", "/api/projects/no_such_project/status")
    check("an unknown project is a 404", st == 404, f"status {st}")
    st, j = c.call("POST", "/api/projects/library/generate",
                   {"subject": "a friendly dragon", "provider": "bogus"})
    check("generate rejects an unknown provider", st == 400, f"status {st} {short(j)}")

    # any web page can POST to localhost; the studio spawns Claude Code, so a
    # foreign Origin (or a DNS-rebinding Host) must be refused
    st, j = c.call("POST", "/api/projects", {"name": "csrf"},
                   headers={"Origin": "https://evil.example"})
    check("a cross-site POST is refused", st == 403, f"status {st} {short(j)}")
    st, j = c.call("POST", "/api/projects", {"name": "same_origin"},
                   headers={"Origin": c.base, "Sec-Fetch-Site": "same-origin"})
    check("a same-origin POST is allowed", st == 200, f"status {st} {short(j)}")
    # another local server reached at a *.localhost name is still another site
    port = int(c.base.rsplit(":", 1)[1])
    st, j = c.call("POST", "/api/projects", {"name": "other_local"},
                   headers={"Host": f"evil.localhost:{port}",
                            "Origin": f"http://evil.localhost:{port + 1}"})
    check("a POST from another local port is refused", st == 403, f"status {st} {short(j)}")
    st, j = c.call("POST", "/api/projects", {"name": "same_site"},
                   headers={"Origin": c.base, "Sec-Fetch-Site": "same-site"})
    check("a same-site (not same-origin) POST is refused", st == 403, f"status {st} {short(j)}")
    st, j = c.call("GET", "/api/projects", headers={"Host": "evil.example"})
    check("a foreign Host header is refused", st == 403, f"status {st} {short(j)}")

    # generate: not set up -> 503 at once, never a spinner, never a paid call
    if isinstance(setup, dict) and (setup.get("nano") or {}).get("key") is False:
        t0 = time.time()
        st, j = c.call("POST", "/api/projects/library/generate",
                       {"subject": "a friendly dragon"}, timeout=30)
        check("generate without a key answers 503 setup:true",
              st == 503 and isinstance(j, dict) and j.get("setup") is True
              and bool(j.get("error")) and bool(j.get("fix")), f"status {st} {short(j)}")
        check("…and fast", time.time() - t0 < 10, f"{time.time() - t0:.1f}s")
    else:
        check("generate 503 check skipped: a Gemini key is visible — refusing to spend", False)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--keep", action="store_true", help="keep the temp folder for inspection")
    args = ap.parse_args()

    port = free_port(args.port)
    if not port:
        sys.exit(f"no free port in {args.port}..8799")
    py = os.path.join(REPO, ".venv", "bin", "python")
    py = py if os.path.exists(py) else sys.executable

    tmp = tempfile.mkdtemp(prefix="studio-smoke-")
    projects, home = os.path.join(tmp, "projects"), os.path.join(tmp, "home")
    os.makedirs(projects)
    os.makedirs(home)
    cfg_path = os.path.join(tmp, "studio.config.json")
    with open(cfg_path, "w") as f:
        json.dump({
            "image_backend": "nano",
            "options": 4,
            "nano": {"key_file": os.path.join(tmp, "no_such_key")},
            "comfyui": {"url": "http://127.0.0.1:9"},     # never probe a real ComfyUI
            "kid": {"grown_up": "a grown-up", "ages": "5 to 9"},
        }, f, indent=2)

    env = {k: v for k, v in os.environ.items()
           if not k.startswith("STUDIO_") and k not in ("GEMINI_API_KEY", "GOOGLE_API_KEY")}
    env.update({"STUDIO_CONFIG": cfg_path, "HOME": home, "PYTHONDONTWRITEBYTECODE": "1"})
    log_path = os.path.join(tmp, "server.log")
    log = open(log_path, "w")
    print(f"smoke test: studio on :{port}, projects {projects}")
    proc = subprocess.Popen([py, SERVER, "--port", str(port), "--projects", projects],
                            cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL)
    check = Checks()
    try:
        c = Client(port)
        deadline = time.time() + 30
        up = False
        while time.time() < deadline and proc.poll() is None:
            try:
                if c.call("GET", "/", timeout=2)[0] == 200:
                    up = True
                    break
            except OSError:
                pass
            time.sleep(0.3)
        if check("server starts", up, f"exit {proc.poll()}"):
            run_checks(c, check)
    finally:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(5)
        log.close()

    total = check.passed + len(check.failed)
    if check.failed:
        print(f"\n{len(check.failed)} of {total} checks FAILED: {', '.join(check.failed)}")
        print(f"server log ({log_path}):")
        with open(log_path) as f:
            print("".join(f.readlines()[-30:]))
    else:
        print(f"\nall {total} checks passed")
    if args.keep:
        print(f"kept {tmp}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return 1 if check.failed else 0


if __name__ == "__main__":
    sys.exit(main())
