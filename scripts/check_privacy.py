#!/usr/bin/env python3
"""check_privacy.py: stops a family's private details from being published. Stdlib only.

    python3 scripts/check_privacy.py [DIR] [--terms FILE] [--no-git]
    python3 scripts/check_privacy.py --self-test

DIR defaults to the repo root. When DIR is the top of a git work tree, the files checked
are `git ls-files --cached --others --exclude-standard` (everything a commit could pick
up). Otherwise it is every file under DIR, hidden ones included, without following
symlinks. scripts/export_public.sh runs it on the exported tree before `git init`, so
there it sees every file.

FAILS (exit 1) on:
  structural    a file that is private because of where it lives or what it's called:
                anything under projects/ except projects/README.md (the data folder:
                people's creations never ship), studio.config.json, .private-terms.txt,
                CLAUDE.local.md / *.local.md, printers/*/log.md, .make3d.log, .env*
                (but not .env.example/.sample/.template), keys and certs, a .venv* folder,
                a face-scan-like mesh (*scan*.stl|ply|obj|3mf), and build junk
                (__pycache__, *.pyc, .DS_Store)
  home-path     an absolute home directory, written as /Users/<name>/, /home/<name>/ or
                C:\\Users\\<name>\\. It leaks a username, and the path won't exist on
                anyone else's machine
  private-term  a word from the terms file (whole word, case-insensitive) in a text file,
                in a binary's metadata, or in a file or folder name. LICENSE's text is
                exempt because it names the author on purpose (its folder names aren't)
  symlink       a link that is absolute or points outside DIR
  unreadable    a file or folder the check couldn't open: unchecked is not clean

WARNS (exit 0) on: pictures outside examples/, studio/static/, docs/ or printers/; PNGs
that carry generator metadata (ComfyUI embeds the whole workflow, prompt included);
JPEGs with EXIF (GPS, camera serials); dangling symlinks.

"Binary metadata" means PNG text chunks, JPEG APP/COM segments, the 80-byte header of a
binary STL, the text header of a binary PLY, and the member names and text members of a
ZIP (a 3MF is a ZIP, and slicers write absolute paths and project names into it). UTF-16
text is decoded and scanned as text. Any other binary (PDF, GIF, WebP, fonts) gets its
printable runs scanned, the way `strings` would: a PDF's /Author lives there.

Findings print as `file:line: kind: detail`. Line 0 means the finding is in the file's
name or in a binary's metadata.

The terms file holds one term per line, with `#` comments. A space inside a term also
matches _ - . or / so "moon base" catches moon_base. Only a LETTER next to a term stops
a match: `_` and digits are word breaks. Earlier versions treated `_` as a letter, and
then digits, and missed every name inside a snake_case folder and every moon2.png.
"""
import argparse
import os
import re
import subprocess
import sys
import zipfile
import zlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TERMS = os.path.join(REPO, ".private-terms.txt")

# Never walked, never reported: git's own store.
SKIP_DIRS = {".git"}
# Walked no further. They're reported once as a single finding, because a venv holds
# thousands of files and one line says enough.
PRUNE_DIRS = {"__pycache__": "junk", "node_modules": "env-dir"}

LICENSE_NAMES = {"LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff"}
IMAGE_OK_PREFIXES = ("examples/", "studio/static/", "docs/", "printers/", ".github/", "assets/")
MESH_EXTS = {".stl", ".ply", ".obj", ".3mf"}
ENV_ALLOW = {".env.example", ".env.sample", ".env.template"}
SECRET_NAMES = {"id_rsa", "id_ed25519", "id_ecdsa", "gemini_key"}
SECRET_EXTS = {".pem", ".key", ".p12", ".pfx"}
PRIVATE_NAMES = {"studio.config.json", "studio.config.json.tmp", ".private-terms.txt",
                 "CLAUDE.local.md", ".make3d.log"}
GENERATOR_KEYS = {"prompt", "workflow", "parameters", "invokeai_metadata"}
TEXT_LIMIT = 50 * 1024 * 1024        # don't read past this; nothing in a repo should be this big
ZIP_MEMBER_LIMIT = 5 * 1024 * 1024

# An absolute home directory. `/Users/<name>/` and `/home/<name>/` only count where a path
# starts: after start-of-text, a space, a quote, `=`, `(` and so on, or after `file://`.
# That way apps/home/test/ is fine. The Windows form can use either slash. "Shared" and the
# obvious placeholders aren't anyone's username.
HOME_PATH = re.compile(
    r"(?:(?<![A-Za-z0-9._/~-])|(?<=file://))(?:/Users|/home)/([A-Za-z0-9._-]+)/"
    r"|[A-Za-z]:[\\/]+Users[\\/]+([A-Za-z0-9._-]+)[\\/]")
# linuxbrew: /home/linuxbrew/.linuxbrew is Homebrew's fixed install path on Linux, not a person.
HOME_PLACEHOLDERS = {"shared", "you", "yourname", "your-name", "username", "user-name", "user",
                     "name", "example", "me", "someone", "runner", "linuxbrew"}


# ----------------------------------------------------------------- terms --
def load_terms(path):
    """Terms from the file: blank lines and # comments skipped, ` # trailing` comments cut."""
    terms = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = re.split(r"\s+#", line, maxsplit=1)[0].strip()
            if line and not line.startswith("#"):
                terms.append(line)
    return terms


def term_regex(terms):
    """One case-insensitive regex for all terms. A term is a whole word: no letter right
    before or after it. Digits, `_`, `-`, `.` and `/` all break words, because names get
    numbered (moon2.png, moon_3) far more often than a real word ends in a digit. A space
    in a term matches any run of separators, an apostrophe matches a curly one too, and a
    plural with no apostrophe ("Zorblaxes", "Zorblaxs", "Fizzies", "Star-Men") still counts as
    the name."""
    alts = []
    for t in sorted(set(terms), key=len, reverse=True):
        words = [w for w in re.split(r"[\s_./-]+", t.strip()) if w]
        if not words:
            continue
        esc = [re.escape(w) for w in words]
        last = words[-1]
        # plurals that change the stem: Fizzy -> Fizzies, Star-Man -> Star-Men
        if re.search(r"[^aeiou\W]y$", last, re.I):
            esc[-1] = re.escape(last[:-1]) + "(?:y|ie)"
        elif re.search(r"man$", last, re.I):
            esc[-1] = re.escape(last[:-3]) + "m[ae]n"
        pat = r"[\s_./-]+".join(esc)
        alts.append(pat.replace("'", "['\u2019]"))
    if not alts:
        return None
    return re.compile(r"(?<![A-Za-z])(?:" + "|".join(alts) + r")(?:e?s)?(?![A-Za-z])", re.I)


# ----------------------------------------------------------------- files --
def git_files(root):
    """Files a commit could contain, relative to root, or None when root isn't the top
    of a git work tree."""
    try:
        top = subprocess.run(["git", "-C", root, "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=30)
        if top.returncode != 0 or os.path.realpath(top.stdout.strip()) != os.path.realpath(root):
            return None
        out = subprocess.run(["git", "-C", root, "ls-files", "-z", "--cached", "--others",
                              "--exclude-standard"], capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return [(p, None) for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


def walk_files(root):
    """Every file and symlink under root as (relpath, pruned_kind). A pruned directory
    comes back once, with a trailing slash."""
    out = []

    def unreadable(err):           # os.walk skips a folder it can't list, silently
        rel = os.path.relpath(err.filename or root, root).replace(os.sep, "/")
        out.append(("" if rel == "." else rel.rstrip("/") + "/", "unreadable"))

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False, onerror=unreadable):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/") + "/"
        keep = []
        for d in sorted(dirnames):
            full = os.path.join(dirpath, d)
            if d in SKIP_DIRS and not os.path.islink(full):
                continue
            if os.path.islink(full):                 # a link to a dir is checked as a link
                out.append((rel_dir + d, None))
            elif d in PRUNE_DIRS:
                out.append((rel_dir + d + "/", PRUNE_DIRS[d]))
            elif d.startswith(".venv"):
                out.append((rel_dir + d + "/", "env-dir"))
            else:
                keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):
            out.append((rel_dir + f, None))
    return out


# ------------------------------------------------------------ structural --
def structural(rel):
    """(kind, detail) when the path alone makes a file private, else None."""
    parts = rel.rstrip("/").split("/")
    base = parts[-1]
    ext = os.path.splitext(base)[1].lower()
    if parts[0] == "projects" and rel != "projects/README.md":
        return "private-dir", "projects/ is the data folder: people's creations never ship"
    if any(p.startswith(".venv") for p in parts):
        return "env-dir", "a virtualenv is per machine (install.sh rebuilds it)"
    if "node_modules" in parts:
        return "env-dir", "installed dependencies are never committed"
    if "__pycache__" in parts or ext in (".pyc", ".pyo") or base == ".DS_Store":
        return "junk", "build/OS junk"
    if base in PRIVATE_NAMES or base.endswith(".local.md") or rel == ".claude/settings.local.json":
        return "private-file", "per-machine settings or private notes"
    if len(parts) == 3 and parts[0] == "printers" and base == "log.md":
        return "private-file", "printers/*/log.md is the private running log"
    if (base == ".env" or base.startswith(".env.")) and base not in ENV_ALLOW:
        return "secret", "environment files hold keys"
    if ext in SECRET_EXTS or base in SECRET_NAMES:
        return "secret", "keys and certificates are never committed"
    if ext in MESH_EXTS and "scan" in base.lower():
        return "biometric", "looks like a 3D scan (a face scan is biometric data)"
    return None


# ---------------------------------------------------------------- content --
def home_hits(text):
    """Distinct home-directory paths in text, placeholders skipped."""
    hits = []
    for m in HOME_PATH.finditer(text):
        name = m.group(1) or m.group(2) or ""
        if name.lower() in HOME_PLACEHOLDERS:
            continue
        if m.group(0) not in hits:
            hits.append(m.group(0))
    return hits


def term_hits(rx, text):
    if rx is None:
        return []
    seen = []
    for m in rx.finditer(text):
        if m.group(0) not in seen:
            seen.append(m.group(0))
    return seen


def scan_text_lines(lines, rx, check_terms):
    """[(line_no, kind, detail)] for an iterable of text lines."""
    out = []
    for i, line in enumerate(lines, 1):
        h = home_hits(line)
        if h:
            out.append((i, "home-path", f"{', '.join(h)}  |  {line.strip()[:160]}"))
        if check_terms:
            t = term_hits(rx, line)
            if t:
                out.append((i, "private-term", "contains " + ", ".join(f'"{x}"' for x in t)))
    return out


def is_text_blob(head):
    return b"\0" not in head


def png_meta(data):
    """[(key, text)] from a PNG's tEXt / zTXt / iTXt chunks, and whether it has eXIf."""
    out, exif, pos = [], False, 8
    while pos + 8 <= len(data):
        n = int.from_bytes(data[pos:pos + 4], "big")
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + n]
        pos += 12 + n
        try:
            if ctype == b"tEXt":
                k, _, v = body.partition(b"\0")
                out.append((k.decode("latin-1"), v.decode("latin-1")))
            elif ctype == b"zTXt":
                k, _, rest = body.partition(b"\0")
                out.append((k.decode("latin-1"), zlib.decompress(rest[1:]).decode("latin-1")))
            elif ctype == b"iTXt":
                k, _, rest = body.partition(b"\0")
                comp, rest = rest[0], rest[2:]
                _lang, _, rest = rest.partition(b"\0")
                _tkw, _, txt = rest.partition(b"\0")
                if comp:
                    txt = zlib.decompress(txt)
                out.append((k.decode("latin-1"), txt.decode("utf-8", "replace")))
            elif ctype == b"eXIf":
                exif = True
            elif ctype == b"IEND":
                break
        except (zlib.error, IndexError, ValueError):
            out.append((ctype.decode("latin-1"), "<unreadable text chunk>"))
    return out, exif


def jpeg_meta(data):
    """Printable runs from a JPEG's APPn / COM segments, and whether it has EXIF."""
    runs, exif, pos = [], False, 2
    while pos + 4 <= len(data) and data[pos] == 0xFF:
        marker = data[pos + 1]
        if marker == 0xDA or marker == 0xD9:        # start of scan / end: no more metadata
            break
        n = int.from_bytes(data[pos + 2:pos + 4], "big")
        seg = data[pos + 4:pos + 2 + n]
        if 0xE0 <= marker <= 0xEF or marker == 0xFE:
            if seg.startswith(b"Exif\0"):
                exif = True
            runs += re.findall(rb"[\x20-\x7e]{4,}", seg)
        pos += 2 + n
    return [r.decode("ascii") for r in runs], exif


def scan_binary(full, rel, rx, check_terms):
    """(findings, warnings) from the metadata a binary file carries."""
    findings, warnings = [], []
    ext = os.path.splitext(rel)[1].lower()

    def check(text, where):
        for _, kind, detail in scan_text_lines(text.splitlines() or [text], rx, check_terms):
            findings.append((0, kind, f"{where}: {detail}"))

    try:
        with open(full, "rb") as f:
            head = f.read(16)
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            with open(full, "rb") as f:
                data = f.read()
            meta, exif = png_meta(data)
            for key, val in meta:
                check(f"{key}={val}", f"PNG text chunk '{key}'")
            gen = sorted({k for k, _ in meta if k.lower() in GENERATOR_KEYS})
            if gen:
                warnings.append((0, "warn-metadata",
                                 f"PNG carries generator metadata ({', '.join(gen)}): the prompt "
                                 f"ships with the picture; strip it unless that's intended"))
            if exif:
                warnings.append((0, "warn-metadata", "PNG carries EXIF (may hold GPS / camera serial)"))
        elif head.startswith(b"\xff\xd8"):
            with open(full, "rb") as f:
                data = f.read(1024 * 1024)
            runs, exif = jpeg_meta(data)
            for r in runs:
                check(r, "JPEG metadata")
            if exif:
                warnings.append((0, "warn-metadata",
                                 "JPEG carries EXIF (may hold GPS / camera serial); strip it"))
        elif zipfile.is_zipfile(full):
            with zipfile.ZipFile(full) as z:
                for info in z.infolist():
                    check(info.filename, f"zip member name '{info.filename}'")
                    if info.is_dir():
                        continue
                    # The head of a big member still counts: a 3MF's 3D/3dmodel.model is
                    # often past the limit, and its <metadata> (Title, Designer) is at the top.
                    with z.open(info) as m:
                        blob = m.read(ZIP_MEMBER_LIMIT)
                    if not is_text_blob(blob[:8192]):
                        continue
                    lines = blob.decode("utf-8", "replace").splitlines()
                    for n, kind, detail in scan_text_lines(lines, rx, check_terms):
                        findings.append((0, kind, f"in {info.filename}:{n}: {detail}"))
        elif ext == ".stl":
            with open(full, "rb") as f:
                header = f.read(80)
            check(header.replace(b"\0", b" ").decode("latin-1"), "STL header")
        elif head.startswith(b"ply"):
            # A binary PLY is an ASCII header (scanners write `comment` lines there) and
            # then raw mesh data, which is only scanned for its header.
            with open(full, "rb") as f:
                header = f.read(64 * 1024).split(b"end_header", 1)[0]
            check(header.decode("latin-1"), "PLY header")
        elif head.startswith((b"\xff\xfe", b"\xfe\xff")):
            # UTF-16 text has a NUL in every ASCII character, so it looked binary.
            with open(full, "rb") as f:
                text = f.read(TEXT_LIMIT).decode("utf-16", "replace")
            for n, kind, detail in scan_text_lines(text.splitlines(), rx, check_terms):
                findings.append((n, kind, f"UTF-16 text: {detail}"))
        elif ext not in MESH_EXTS:
            # Anything else (PDF, GIF, WebP, fonts): what metadata it has is printable
            # runs, like a PDF's /Author or an XMP packet. Mesh data is skipped: random
            # floats make printable runs too, and nothing is written there.
            with open(full, "rb") as f:
                runs = re.findall(rb"[\x20-\x7e]{4,}", f.read(TEXT_LIMIT))
            check("\n".join(r.decode("ascii") for r in runs), "printable strings")
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError, EOFError, zlib.error,
            NotImplementedError) as e:        # NotImplementedError: a zip compression we lack
        # unchecked is not clean: a 3MF that won't open may still hold a name
        findings.append((0, "unreadable", f"could not check its metadata: {e}"))
    return findings, warnings


# ------------------------------------------------------------------- scan --
def scan(root, terms=(), use_git=True):
    """Check a tree. Returns (findings, warnings, scanned_text_files); each finding is
    (relpath, line, kind, detail)."""
    root = os.path.abspath(root)
    real_root = os.path.realpath(root)
    rx = term_regex(terms)
    entries = (git_files(root) if use_git else None) or walk_files(root)
    findings, warnings, scanned = [], [], 0

    for rel, pruned in entries:
        rel = rel.replace(os.sep, "/")
        full = os.path.join(root, rel.rstrip("/"))
        base = os.path.basename(rel.rstrip("/"))
        check_terms = base not in LICENSE_NAMES

        hit = structural(rel)
        if pruned and not hit:
            hit = (pruned, "could not list this folder to check it" if pruned == "unreadable"
                   else "never committed")
        if hit:
            findings.append((rel, 0, hit[0], hit[1]))
            continue

        # File and folder names count too: a picture named after a child leaks just as
        # surely as text does. A LICENSE's own name is exempt, its folders aren't.
        t = term_hits(rx, rel if check_terms else os.path.dirname(rel.rstrip("/")))
        if t:
            findings.append((rel, 0, "private-term", "path contains " + ", ".join(f'"{x}"' for x in t)))

        if os.path.islink(full):
            target = os.readlink(full)
            resolved = os.path.realpath(os.path.join(os.path.dirname(full), target))
            for h in home_hits(target):
                findings.append((rel, 0, "home-path", f"symlink target {h}"))
            if os.path.isabs(target):
                findings.append((rel, 0, "symlink", f"absolute target {target!r}: breaks on every other machine"))
            elif resolved != real_root and not resolved.startswith(real_root + os.sep):
                findings.append((rel, 0, "symlink", f"target {target!r} points outside the tree"))
            elif not os.path.exists(full):
                warnings.append((rel, 0, "warn-symlink", f"dangling: {target!r} does not exist"))
            continue
        if not os.path.isfile(full):
            continue                                  # deleted but still in the git index

        ext = os.path.splitext(base)[1].lower()
        if ext in IMAGE_EXTS and not rel.startswith(IMAGE_OK_PREFIXES):
            warnings.append((rel, 0, "warn-image",
                             "picture outside examples/, studio/static/, docs/, printers/: "
                             "look at it, make sure it shows nothing personal"))
        try:
            with open(full, "rb") as f:
                head = f.read(8192)
        except OSError as e:
            findings.append((rel, 0, "unreadable", f"could not open it to check: {e}"))
            continue
        if is_text_blob(head) and os.path.getsize(full) <= TEXT_LIMIT:
            scanned += 1
            with open(full, encoding="utf-8", errors="replace") as f:
                for n, kind, detail in scan_text_lines(f, rx, check_terms):
                    findings.append((rel, n, kind, detail))
        else:
            fb, wb = scan_binary(full, rel, rx, check_terms)
            findings += [(rel,) + x for x in fb]
            warnings += [(rel,) + x for x in wb]
    return findings, warnings, scanned


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fail when private family data would be published.")
    ap.add_argument("dir", nargs="?", default=REPO, help="tree to check (default: the repo)")
    ap.add_argument("--terms", help=f"private terms file (default: {DEFAULT_TERMS} if present)")
    ap.add_argument("--no-git", action="store_true", help="walk every file even in a git work tree")
    ap.add_argument("--self-test", action="store_true", help="plant leaks in a temp tree and check each is caught")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()
    if not os.path.isdir(args.dir):
        print(f"check_privacy: {args.dir} is not a directory", file=sys.stderr)
        return 2
    terms_file = args.terms or (DEFAULT_TERMS if os.path.isfile(DEFAULT_TERMS) else None)
    terms = []
    if terms_file:
        if not os.path.isfile(terms_file):
            # a typo here must not quietly drop the check to structural-only
            print(f"check_privacy: terms file {terms_file} not found", file=sys.stderr)
            return 2
        terms = load_terms(terms_file)

    findings, warnings, scanned = scan(args.dir, terms, use_git=not args.no_git)
    for rel, line, kind, detail in sorted(warnings):
        print(f"{rel}:{line}: {kind}: {detail}")
    for rel, line, kind, detail in sorted(findings):
        print(f"{rel}:{line}: {kind}: {detail}")
    where = (f"{len(terms)} private term(s) from {terms_file}" if terms
             else f"{terms_file} holds no terms: structural + home-path checks only" if terms_file
             else "no private terms file: structural + home-path checks only")
    status = "ok" if not findings else f"{len(findings)} finding(s)"
    print(f"privacy check: {status}, {len(warnings)} warning(s); {scanned} text files scanned; {where}")
    return 1 if findings else 0


# -------------------------------------------------------------- self-test --
def _png(text_chunks=()):
    """A 1x1 PNG, optionally carrying tEXt chunks."""
    def chunk(ctype, body):
        return (len(body).to_bytes(4, "big") + ctype + body
                + zlib.crc32(ctype + body).to_bytes(4, "big"))
    ihdr = (1).to_bytes(4, "big") * 2 + bytes([8, 2, 0, 0, 0])
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
    for k, v in text_chunks:
        out += chunk(b"tEXt", k.encode("latin-1") + b"\0" + v.encode("latin-1"))
    return out + chunk(b"IDAT", zlib.compress(b"\0\xff\xff\xff")) + chunk(b"IEND", b"")


def self_test():
    """Build a tree with one planted leak per rule, scan it, and assert the findings are
    exactly the planted ones: every leak caught, nothing clean flagged."""
    import io
    import shutil
    import tempfile

    # Built at runtime, so this file never holds a home path itself.
    users, home = "/" + "Users", "/" + "home"
    terms = ["Zorblax", "Quuxley Fern", "Zed's", "moon base", "Fizzy", "Star-Man"]
    stl_header = b"solid zorblax_part".ljust(80, b"\0") + (0).to_bytes(4, "little")
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("Metadata/project_settings.config", f"x\nout = {users}/zed/Desktop/plate\n")
        z.writestr("3D/zorblax.model", "<model/>")
        z.writestr("3D/clean.model", "<model/>")
    # a member past ZIP_MEMBER_LIMIT: its head is still read (3dmodel.model is often huge)
    bigbuf = io.BytesIO()
    with zipfile.ZipFile(bigbuf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("3D/3dmodel.model", '<metadata name="Title">zorblax</metadata>\n'
                   + "x" * (ZIP_MEMBER_LIMIT + 1024))
    files = {
        # clean: must produce nothing
        "README.md": ("fine: /usr/local/bin, ~/ComfyUI, apps/home/test/, Zorblaxian, quuxleyfern,\n"
                      "Zorblaxesque, Zorblaxess, fizzing, starmania,\n"
                      f"zorblaxsf, {home}/linuxbrew/.linuxbrew/bin, {home}/user/x\n"),
        "docs/clean.pdf": b"%PDF-1.4\n\0\0\n1 0 obj << /Author (Someone Else) >> endobj\n",
        "docs/clean.ply": b"ply\nformat binary_little_endian 1.0\nend_header\n" + b"\0zorblax\0",
        "docs/shared.md": f"{users}/Shared/x and {users}/you/x are placeholders\n",
        "printers/acme/profile.md": "bed 260 mm\n",
        ".env.example": "GEMINI_API_KEY=\n",
        "projects/README.md": "Your creations live here.\n",
        "examples/clean.png": _png(),
        "LICENSE": "Copyright (c) 2026 Zorblax\n",            # terms exempt
        # planted leaks
        "docs/guide.md": f"line one\nsee {users}/zed/notes.txt\n",
        "docs/win.md": "C:\\" + "Users\\zed\\x\n",
        "docs/fwd.md": "C:/" + "Users/zed/x\n",
        "docs/linux.md": f"({home}/zed/x)\n",
        "docs/url.md": f"<a href='file://{users}/zed/x'>\n",
        "docs/kid.md": "a\nb\nmade for the hb_j1_zorblax_bucket day\n",   # _ on both sides
        "docs/multi.md": "the Quuxley-Fern plate\n",
        "docs/apos.md": "Zed\u2019s printer\n",
        "docs/plural.md": "fine\ntwo Zorblaxes met the Zorblaxs\nthe Fizzies and the Star-Men\n",
        "docs/board.md": "see projects/moon_base/\n",
        "docs/digit.md": "photo zorblax2.png\nphoto 2zorblax.png\n",     # digits break words
        "docs/notes16.txt": "﻿made for Zorblax\n".encode("utf-16-le"),   # BOM + NULs
        "docs/manual.pdf": (b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n\0\0\n"
                            b"1 0 obj << /Author (Quuxley Fern) >> endobj\n"),
        "docs/head.ply": (b"ply\nformat binary_little_endian 1.0\ncomment by zorblax\n"
                          b"end_header\n" + b"\0" * 24),
        "zorblax_stuff/LICENSE": "MIT\n",                     # text exempt, folder name isn't
        "assets/zorblax.txt": "nothing in here\n",
        "LICENSE.extra": f"{users}/zed/\n",                     # not exempt from home paths
        "projects/kid_thing/model.stl": stl_header,
        "studio.config.json": "{}\n",
        ".private-terms.txt": "Zorblax\n",
        "CLAUDE.local.md": "notes\n",
        "printers/acme/log.md": "clogged on a Tuesday\n",
        ".env": "GEMINI_API_KEY=abc\n",
        "certs/server.pem": "x\n",
        "certs/server.key": "x\n",
        ".venv/lib/site.py": "x\n",
        "meshes/head_scan.stl": b"\0" * 84,
        "studio/__pycache__/server.cpython-314.pyc": b"\0\1",
        "studio/.DS_Store": b"\0\0\0\1Bud1",
        "examples/gen.png": _png([("prompt", '{"text": "a friendly zorblax"}')]),
        "misc/photo.png": _png(),
        "models/part.stl": stl_header,
        "models/plate.3mf": zbuf.getvalue(),
        "models/big.3mf": bigbuf.getvalue(),
        "docs/locked.md": "zorblax\n",                       # chmod 000 below
    }
    expected = {
        ("docs/guide.md", 2, "home-path"), ("docs/win.md", 1, "home-path"),
        ("docs/fwd.md", 1, "home-path"), ("docs/linux.md", 1, "home-path"),
        ("docs/url.md", 1, "home-path"), ("docs/kid.md", 3, "private-term"),
        ("docs/multi.md", 1, "private-term"), ("docs/apos.md", 1, "private-term"),
        ("docs/plural.md", 2, "private-term"), ("docs/plural.md", 3, "private-term"),
        ("docs/board.md", 1, "private-term"),
        ("assets/zorblax.txt", 0, "private-term"), ("LICENSE.extra", 1, "home-path"),
        ("projects/kid_thing/model.stl", 0, "private-dir"),
        ("studio.config.json", 0, "private-file"), (".private-terms.txt", 0, "private-file"),
        ("CLAUDE.local.md", 0, "private-file"), ("printers/acme/log.md", 0, "private-file"),
        (".env", 0, "secret"), ("certs/server.pem", 0, "secret"), ("certs/server.key", 0, "secret"),
        (".venv/", 0, "env-dir"), ("meshes/head_scan.stl", 0, "biometric"),
        ("studio/__pycache__/", 0, "junk"), ("studio/.DS_Store", 0, "junk"),
        ("examples/gen.png", 0, "private-term"), ("models/part.stl", 0, "private-term"),
        ("models/plate.3mf", 0, "home-path"), ("models/plate.3mf", 0, "private-term"),
        ("links/abs", 0, "symlink"), ("links/out", 0, "symlink"),
        ("docs/digit.md", 1, "private-term"), ("docs/digit.md", 2, "private-term"),
        ("docs/notes16.txt", 1, "private-term"),
        ("docs/manual.pdf", 0, "private-term"), ("docs/head.ply", 0, "private-term"),
        ("zorblax_stuff/LICENSE", 0, "private-term"), ("models/big.3mf", 0, "private-term"),
    }
    expected_warnings = {
        ("examples/gen.png", "warn-metadata"), ("misc/photo.png", "warn-image"),
        ("links/dangling", "warn-symlink"),
    }

    failures = []
    tmp = tempfile.mkdtemp(prefix="check_privacy_")
    try:
        root = os.path.join(tmp, "tree")
        for rel, body in files.items():
            p = os.path.join(root, *rel.split("/"))
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb" if isinstance(body, bytes) else "w",
                      **({} if isinstance(body, bytes) else {"encoding": "utf-8"})) as f:
                f.write(body)
        os.makedirs(os.path.join(root, "links"))
        os.symlink("../docs", os.path.join(root, "links", "good"))          # fine
        os.symlink("/etc", os.path.join(root, "links", "abs"))              # absolute
        os.symlink("../../outside", os.path.join(root, "links", "out"))     # escapes the tree
        os.symlink("../nope", os.path.join(root, "links", "dangling"))      # inside but missing
        # what can't be read is a finding, not a pass (root reads everything: skip there)
        locked_dir = os.path.join(root, "locked_dir")
        os.makedirs(locked_dir)
        if hasattr(os, "geteuid") and os.geteuid() != 0:
            os.chmod(os.path.join(root, "docs", "locked.md"), 0)
            os.chmod(locked_dir, 0)
            expected |= {("docs/locked.md", 0, "unreadable"), ("locked_dir/", 0, "unreadable")}
        else:
            expected.add(("docs/locked.md", 1, "private-term"))

        findings, warnings, _ = scan(root, terms, use_git=False)
        got = {(r, ln, k) for r, ln, k, _ in findings}
        for miss in sorted(expected - got):
            failures.append(f"leak NOT caught: {miss}")
        for extra in sorted(got - expected):
            failures.append(f"false positive: {extra}")
        gotw = {(r, k) for r, _, k, _ in warnings}
        for miss in sorted(expected_warnings - gotw):
            failures.append(f"warning missing: {miss}")
        for extra in sorted(gotw - expected_warnings):
            failures.append(f"unexpected warning: {extra}")

        # the CLI: findings -> 1, clean -> 0, a mistyped terms file -> 2
        terms_file = os.path.join(tmp, "terms.txt")
        with open(terms_file, "w", encoding="utf-8") as f:
            f.write("# comment\n" + "\n".join(terms) + "\nTrailing  # inline comment\n")
        if load_terms(terms_file) != terms + ["Trailing"]:
            failures.append(f"load_terms parsed {load_terms(terms_file)!r}")
        quiet = io.StringIO()
        stdout, stderr = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = quiet
        try:
            rc_dirty = main([root, "--terms", terms_file, "--no-git"])
            clean = os.path.join(tmp, "clean")
            os.makedirs(os.path.join(clean, "docs"))
            with open(os.path.join(clean, "docs", "a.md"), "w", encoding="utf-8") as f:
                f.write("nothing to see\n")
            rc_clean = main([clean, "--terms", terms_file])
            rc_missing = main([clean, "--terms", os.path.join(tmp, "nope.txt")])
        finally:
            sys.stdout, sys.stderr = stdout, stderr
        if (rc_dirty, rc_clean, rc_missing) != (1, 0, 2):
            failures.append(f"exit codes dirty/clean/missing = {rc_dirty}/{rc_clean}/{rc_missing}, want 1/0/2")

        # git mode: an ignored file is not part of a commit, so it isn't reported
        if shutil.which("git"):
            g = os.path.join(tmp, "gitrepo")
            os.makedirs(g)
            subprocess.run(["git", "init", "-q", g], check=True)
            with open(os.path.join(g, ".gitignore"), "w") as f:
                f.write("ignored.md\n")
            # .git/ is never walked (export runs this on a fresh `git init` tree)
            for name in ("ignored.md", "kept.md", os.path.join(".git", "description")):
                with open(os.path.join(g, name), "w") as f:
                    f.write("zorblax\n")
            got_git = {r for r, _, _, _ in scan(g, terms)[0]}
            got_walk = {r for r, _, _, _ in scan(g, terms, use_git=False)[0]}
            if got_git != {"kept.md"}:
                failures.append(f"git mode reported {sorted(got_git)}, want ['kept.md']")
            if got_walk != {"ignored.md", "kept.md"}:
                failures.append(f"walk mode reported {sorted(got_walk)}, want both files")
    finally:
        for p in (os.path.join(tmp, "tree", "locked_dir"),
                  os.path.join(tmp, "tree", "docs", "locked.md")):
            if os.path.exists(p):
                os.chmod(p, 0o700)
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("check_privacy self-test FAILED:")
        for f in failures:
            print("  " + f)
        return 1
    print(f"check_privacy self-test: ok ({len(expected)} planted leaks caught, "
          f"{len(expected_warnings)} warnings, no false positives, CLI exit codes, git mode)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
