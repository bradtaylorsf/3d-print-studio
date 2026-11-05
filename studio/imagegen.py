#!/usr/bin/env python3
"""imagegen.py — the studio's picture makers. Stdlib only (resvg_py is loaded
lazily, and only by the Claude backend).

    generate(pdir, subject, backend, style, count, cfg)
        -> (files, titles, used_backend, errors)

A child asks for something; `count` options (4 by default) are drawn in
parallel and saved into <pdir>/refs/ as gen_<slug>.png, gen_<slug>_2.png, …
(never overwriting). Three backends:

    claude   the user's OWN Claude Code CLI, headless (`claude -p`), draws each
             option as an SVG: flat colours, chunky shapes — exactly what the
             coin tracer wants. The SVG is sanitized, rasterized with resvg to
             the PNG, and kept as <pdir>/vectors/<stem>.svg so a Make me 3D
             build can read exact shapes and colours. ~25 s per picture, all
             options at once. No GPU, no API key — it uses the CLI's login.
    comfyui  a local ComfyUI running Z-Image Turbo. Free per picture; ComfyUI
             runs one queue, so the options render one after another.
    nano     Google Nano Banana (a Gemini image model). Needs a Gemini API key.

Partial success is success: whatever drew is saved and the rest come back as
error strings. Every setting comes from studio/config.py.
"""
import json
import os
import re
import subprocess
import tempfile
import threading
import time
import xml.etree.ElementTree as ET

import config

BACKENDS = config.BACKENDS                  # ("claude", "comfyui", "nano")
STYLES = ("sticker", "turnaround", "chip")
MAX_OPTIONS = 8
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

CLAUDE_TIMEOUT_S = 240                      # one picture; ~25 s is normal on Opus
LOGIN_MSG = "Claude Code isn't logged in — run `claude`, then /login"
NANO_KEY_MSG = "Gemini rejected the API key — check GEMINI_API_KEY or the nano.key_file"
# failures that are setup, not bad luck: when every option fails with one of
# these, the studio answers 503 "needs setup" (kid mode: "ask a grown-up")
SETUP_FIXES = {
    LOGIN_MSG: "run `claude` in a terminal, then /login",
    NANO_KEY_MSG: "put a valid key in GEMINI_API_KEY or the nano.key_file, or re-run ./install.sh",
}

# ---------------------------------------------------------------- prompts --
# comfyui / nano: one prompt per style, the same for every option (a different
# seed is what varies them).

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

# claude: each option is its own headless call with a different take, so four
# calls give four genuinely different pictures instead of four near-copies.
TAKES = (
    "the classic, most recognizable version",
    "extra cute and round",
    "in a fun action pose",
    "with a playful surprise twist (a hat, a friend, a silly detail)",
)
CLAUDE_SYSTEM = ("You are an illustrator for a kids' 3D-printing app. "
                 "You output only what is asked.")
_COMPOSITION = {
    "sticker": "one chunky subject centred filling ~70% of the frame; "
               "thick limbs, no thin spikes; die-cut sticker style.",
    "turnaround": "the SAME subject three times in a row — front, side profile, "
                  "three-quarter — evenly spaced, same size, consistent; "
                  "thick limbs, no thin spikes; chunky toy style.",
    "chip": "one single solid silhouette centred filling ~65% of the frame; "
            "every part broad and solid, no thin spikes; readable as a tiny stamp.",
}


def claude_prompt(subject, take, style="sticker", ages="5 to 9"):
    """The verified sticker wording, with the composition swapped per style.
    Extend carefully: the JSON-only reply and the SVG rules are what make the
    output parse and trace."""
    subject = subject.replace('"', "'")
    if style == "chip":
        bg = "first element a full black rect background"
        fills = "one flat solid white (#fff) silhouette only"
    else:
        bg = "first element a full white rect background"
        fills = "flat solid fills only, 3-4 bright colours plus optional thick dark (#222) outlines"
    return (
        f'A child (age {ages}) asked for: "{subject}". Draw ONE option: {take}. '
        "If the request isn't right for young children, draw a friendly, wholesome "
        "version of the idea instead. Reply with ONLY a JSON object, no prose, no code "
        'fence: {"title": "<2-5 word kid-friendly name>", "svg": "<svg ...>...</svg>"}. '
        f'SVG rules: viewBox="0 0 1024 1024"; {bg}; {fills}; no gradients, filters, '
        f"text, images, or opacity; {_COMPOSITION.get(style, _COMPOSITION['sticker'])}"
    )


def raster_prompt(subject, style):
    return {"chip": CHIP_PROMPT, "sticker": STICKER_PROMPT}.get(
        style, TURNAROUND_PROMPT).format(subject=subject)


def reply_text(subject, n):
    """The sentence kid mode reads aloud when the options arrive."""
    s = re.sub(r"\s+", " ", subject).strip().rstrip(".!?,;:")
    if n == 1:
        return f"I drew a picture of {s}! Do you like it?"
    return f"I drew {n} pictures of {s}! Which one do you like best?"


class ImageError(Exception):
    """A failure worth showing to a person, already worded for them."""


# ------------------------------------------------------------------ files --
def unique_path(directory, name):
    """refs/foo.png, refs/foo_2.png, ... — never overwrite."""
    os.makedirs(directory, exist_ok=True)
    base, ext = os.path.splitext(name)
    path, n = os.path.join(directory, name), 2
    while os.path.exists(path):
        path = os.path.join(directory, f"{base}_{n}{ext}")
        n += 1
    return path


def save_unique(directory, name, data):
    """unique_path + an exclusive create, so two generate requests landing at
    the same moment can't both claim gen_dragon.png."""
    while True:
        path = unique_path(directory, name)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            continue
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return path


def to_png(blob):
    """(bytes, ext). Nano Banana sometimes answers with a JPEG; refs are PNG
    when Pillow can convert it, else the JPEG is kept as-is."""
    if blob[:8] == PNG_MAGIC:
        return blob, ".png"
    try:
        import io
        from PIL import Image
        out = io.BytesIO()
        Image.open(io.BytesIO(blob)).convert("RGB").save(out, "PNG")
        return out.getvalue(), ".png"
    except Exception:
        return blob, ".jpg"


# ------------------------------------------------------------ SVG safety --
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)
MAX_SVG = 2 * 1024 * 1024
# anything that can run code, pull in another document, or rewrite an href
# later — plus the non-drawing text elements: the saved SVG is read by a
# bypassPermissions Make-me-3D build, and a <desc> is a free place for words
# aimed at it rather than at the picture
_BANNED = {"script", "foreignobject", "image", "iframe", "embed", "object", "audio",
           "video", "canvas", "set", "animate", "animatetransform", "animatemotion",
           "handler", "listener", "desc", "title", "metadata",
           # not flat fills (the prompt forbids them), and resvg renders a
           # pattern tile at its own size: a 10^6 px tile ate 2 GB and climbing
           "pattern", "filter"}
CANVAS = 1024                               # px; the PNG is always CANVAS x CANVAS
# url(...) that isn't url(#id); the lookahead sits right after "(" so leading
# whitespace can't be backtracked around it
_EXT_URL = re.compile(r"url\((?!\s*['\"]?\s*#)[^)]*\)", re.I)
_CSS_FILTER = re.compile(r"(?<![\w-])filter\s*:[^;}]*;?", re.I)


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _clean(el):
    for child in list(el):
        tag = _local(child.tag).lower() if isinstance(child.tag, str) else ""
        if not tag or tag in _BANNED or tag.startswith("fe"):
            el.remove(child)
            continue
        _clean(child)
    for k in list(el.attrib):
        name, v = _local(k).lower(), el.attrib[k]
        if name.startswith("on") or "javascript:" in v.lower().replace(" ", ""):
            del el.attrib[k]
        elif name == "filter":              # a shape pointing at a removed filter isn't drawn at all
            del el.attrib[k]
        elif name == "href" and not v.strip().startswith("#"):
            del el.attrib[k]
        else:
            if name == "style":
                v = _CSS_FILTER.sub("", v)
            if "url(" in v.lower():
                v = _EXT_URL.sub("none", v)
            el.attrib[k] = v
    if _local(el.tag).lower() == "style" and el.text:
        el.text = re.sub(r"@import[^;]*;?", "",
                         _CSS_FILTER.sub("", _EXT_URL.sub("none", el.text)), flags=re.I)


MAX_DEPTH = 40                              # element nesting; a real drawing needs < 10


def _depth(root):
    deepest, stack = 0, [(root, 1)]
    while stack:
        el, d = stack.pop()
        deepest = max(deepest, d)
        if deepest > MAX_DEPTH:
            break
        stack.extend((c, d + 1) for c in el)
    return deepest


def _href(el):
    for k, v in el.attrib.items():
        if _local(k).lower() == "href":
            return v.strip()
    return ""


def _limit_use(root):
    """<use> may point at plain shapes only, never at something that holds
    another <use>: ten uses of a group of ten uses, nine deep, is 10^9 shapes
    for the renderer — the billion-laughs attack without an entity."""
    parent = {c: p for p in root.iter() for c in p}
    holders = {el.get("id") for el in root.iter()
               if el.get("id") and any(_local(d.tag).lower() == "use" for d in el.iter())}
    for el in list(root.iter()):
        if _local(el.tag).lower() == "use" and _href(el).lstrip("#") in holders \
                and el in parent:
            parent[el].remove(el)


def _square_canvas(root):
    """Pin the canvas to CANVAS x CANVAS. resvg sizes the PNG from the SVG's
    own aspect ratio: a viewBox of "0 0 1 100000" asked for a 1024 x 102
    million pixel image and took 25 GB of memory before it was killed. The
    drawing keeps its viewBox and is fitted inside (preserveAspectRatio)."""
    def num(v):
        m = re.match(r"\s*([0-9.]+)\s*(px)?\s*$", v or "")
        return float(m.group(1)) if m else None
    vb = (root.get("viewBox") or "").replace(",", " ").split()
    try:
        ok = len(vb) == 4 and float(vb[2]) > 0 and float(vb[3]) > 0
    except ValueError:
        ok = False
    if not ok:
        w, h = num(root.get("width")), num(root.get("height"))
        root.set("viewBox", f"0 0 {w:g} {h:g}" if w and h else f"0 0 {CANVAS} {CANVAS}")
    root.set("width", str(CANVAS))
    root.set("height", str(CANVAS))


def sanitize_svg(svg):
    """The model's SVG is untrusted text. Keep the drawing, drop everything
    that isn't one: <script>, <foreignObject>, <image>, animation that can
    rewrite attributes, on*= handlers, and any href / url() that points
    outside the document. DOCTYPE/ENTITY is refused outright (entity bombs),
    nested <use> fan-out is cut, and the canvas is pinned square so the
    render's size can't be blown up by a stretched viewBox."""
    if not svg or len(svg) > MAX_SVG:
        raise ImageError("the drawing was empty or far too big")
    if re.search(r"<!\s*(DOCTYPE|ENTITY)", svg, re.I):
        raise ImageError("the drawing carried a DOCTYPE/ENTITY — refused")
    m = re.search(r"<svg\b[^>]*>", svg)
    if not m:
        raise ImageError("Claude replied without an <svg> drawing")
    svg = svg[m.start():]
    end = svg.rfind("</svg>")
    if end >= 0:
        svg = svg[:end + len("</svg>")]
    tag = m.group(0)
    new_tag = tag
    if "xmlns=" not in tag:
        new_tag = new_tag.replace("<svg", f'<svg xmlns="{SVG_NS}"', 1)
    if "xlink:" in svg and "xmlns:xlink" not in tag:
        new_tag = new_tag.replace("<svg", f'<svg xmlns:xlink="{XLINK_NS}"', 1)
    svg = new_tag + svg[len(tag):]
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as e:
        raise ImageError(f"the drawing was not valid SVG ({e})") from e
    if _local(root.tag) != "svg":
        raise ImageError("the drawing was not an <svg> document")
    if _depth(root) > MAX_DEPTH:
        # every <g opacity> / clip / mask level is a full-canvas layer in
        # resvg: 200 nested groups took 4 s and most of a gigabyte
        raise ImageError("the drawing was nested far too deep")
    _clean(root)
    _limit_use(root)
    _square_canvas(root)
    return ET.tostring(root, encoding="unicode")


def rasterize(svg, width=CANVAS):
    """SVG -> PNG bytes with resvg, on white (the coin tracer reads the
    background from the border colour, so it must be solid)."""
    try:
        import resvg_py
    except ImportError as e:
        raise ImageError("resvg_py is not installed (turns Claude's drawings into "
                         "PNGs) — .venv/bin/pip install -r requirements.txt") from e
    try:
        try:
            png = resvg_py.svg_to_bytes(svg_string=svg, width=width, background="#ffffff")
        except TypeError:                   # an older resvg_py without `background`
            png = resvg_py.svg_to_bytes(svg_string=svg, width=width)
    except ValueError as e:
        raise ImageError(f"could not render the drawing ({e})") from e
    png = bytes(png)
    if not png.startswith(PNG_MAGIC):
        raise ImageError("resvg returned something that isn't a PNG")
    return png


# ---------------------------------------------------------------- claude --
def _clean_title(t):
    if not isinstance(t, str):
        return None
    t = re.sub(r"[\x00-\x1f<>]", "", t).strip().strip('"').strip()
    return t[:60] or None


def claude_error(text, stdout, stderr, rc):
    blob = "\n".join(x for x in (text, stdout, stderr) if x)
    low = blob.lower()
    if ("not logged in" in low or "/login" in low or "invalid api key" in low
            or "authenticat" in low or "oauth token" in low):
        return LOGIN_MSG
    lines = [ln.strip() for ln in (text or stderr or stdout or "").splitlines() if ln.strip()]
    return (("Claude: " + re.sub(r"[<>\x00-\x1f]", "", lines[-1]))[:208] if lines
            else f"Claude exited with code {rc}")


def parse_claude_output(rc, stdout, stderr):
    """`claude -p --output-format json` -> (title, svg). The reply should be
    pure JSON; take first `{` to last `}` of `result`, and fall back to the
    first <svg>…</svg> when the JSON doesn't parse (an unescaped quote)."""
    out = (stdout or "").strip()
    data = None
    for cand in (out, (out.splitlines() or [""])[-1]):
        try:
            data = json.loads(cand)
            break
        except ValueError:
            continue
    if isinstance(data, list):
        # `verbose` on in the user's Claude settings turns the json output
        # into the whole message list; the answer is its "result" entry
        data = next((m for m in reversed(data)
                     if isinstance(m, dict) and m.get("type") == "result"), None)
    text = data.get("result") if isinstance(data, dict) else None
    if rc != 0 or not isinstance(data, dict) or data.get("is_error"):
        raise ImageError(claude_error(text if isinstance(text, str) else "", stdout, stderr, rc))
    text = text if isinstance(text, str) else ""
    title = svg = None
    s, e = text.find("{"), text.rfind("}")
    if s >= 0 and e > s:
        try:
            obj = json.loads(text[s:e + 1])
            if isinstance(obj, dict):
                svg, title = obj.get("svg"), obj.get("title")
        except ValueError:
            pass
    if not isinstance(svg, str) or "<svg" not in svg:
        m = re.search(r"<svg[\s\S]*?</svg>", text)
        if not m:
            raise ImageError("Claude replied without a drawing")
        svg = m.group(0)
        if '\\"' in svg:                    # it was inside a JSON string that didn't parse
            svg = svg.replace('\\"', '"').replace("\\n", "\n").replace("\\/", "/")
        tm = re.search(r'"title"\s*:\s*"([^"]{1,80})"', text)
        title = tm.group(1) if tm else None
    return _clean_title(title), svg


def claude_option(cfg, subject, style, take, timeout=CLAUDE_TIMEOUT_S):
    """One picture from the user's own Claude Code CLI. Returns (png, svg, title)."""
    binpath = config.claude_bin(cfg)
    if not binpath:
        raise ImageError("Claude Code CLI not found — install it: "
                         "curl -fsSL https://claude.ai/install.sh | bash")
    prompt = claude_prompt(subject, take, style,
                           config.get_path(cfg, "kid.ages") or "5 to 9")
    cmd = [binpath, "-p", prompt,
           "--model", config.get_path(cfg, "claude.draw_model") or "claude-opus-5-5",
           "--output-format", "json", "--strict-mcp-config", "--tools", "",
           "--no-session-persistence", "--system-prompt", CLAUDE_SYSTEM]
    # a fresh empty cwd: no repo CLAUDE.md, skills or settings get loaded into a
    # drawing call — it needs none of them and they cost time on every picture
    with tempfile.TemporaryDirectory(prefix="studio-draw-") as tmp:
        try:
            r = subprocess.run(cmd, cwd=tmp, capture_output=True, text=True,
                               timeout=timeout, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as e:
            raise ImageError(f"Claude took longer than {timeout} s to draw") from e
        except OSError as e:
            raise ImageError(f"could not run {binpath}: {e.strerror or e}") from e
    title, svg = parse_claude_output(r.returncode, r.stdout, r.stderr)
    svg = sanitize_svg(svg)
    return rasterize(svg), svg, title


# --------------------------------------------------------------- comfyui --
def _http_error_detail(e):
    try:
        body = json.loads(e.read().decode("utf-8", "replace"))
    except Exception:
        return f"HTTP {e.code}"
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        msg = err.get("message") or err.get("type")
        details = err.get("details")
        return f"{msg} {details}".strip() if details else (msg or f"HTTP {e.code}")
    return str(err or body)[:200]


def gen_comfy(prompt, url, models, steps=8, timeout=240):
    """One image from a local ComfyUI (Z-Image Turbo). Returns PNG bytes."""
    import time
    import urllib.error
    import urllib.request
    from urllib.parse import urlencode
    seed = int.from_bytes(os.urandom(4), "big") % (2 ** 31)
    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {
            "unet_name": models["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": models["clip"], "type": "lumina2", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": models["vae"]}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["2", 0]}},
        "5": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["4", 0]}},
        "6": {"class_type": "EmptySD3LatentImage", "inputs": {
            "width": 1024, "height": 1024, "batch_size": 1}},
        "7": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
        "8": {"class_type": "KSampler", "inputs": {
            "model": ["7", 0], "positive": ["4", 0], "negative": ["5", 0],
            "latent_image": ["6", 0], "seed": seed, "steps": int(steps), "cfg": 1.0,
            "sampler_name": "res_multistep", "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "SaveImage", "inputs": {
            "images": ["9", 0], "filename_prefix": "studio_gen"}},
    }

    def call(path, data=None):
        req = urllib.request.Request(
            f"{url}{path}",
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Content-Type": "application/json"} if data is not None else {})
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)

    try:
        pid = call("/prompt", {"prompt": wf})["prompt_id"]
    except urllib.error.HTTPError as e:
        raise ImageError(f"ComfyUI refused the job: {_http_error_detail(e)}") from e
    except OSError as e:
        raise ImageError(f"ComfyUI at {url} is not answering ({e})") from e
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = call(f"/history/{pid}")
        if pid in h:
            status = h[pid].get("status", {})
            if status.get("status_str") == "error":
                msgs = [m[1].get("exception_message", "") for m in status.get("messages", [])
                        if isinstance(m, list) and len(m) > 1 and m[0] == "execution_error"
                        and isinstance(m[1], dict)]
                raise ImageError("ComfyUI execution error"
                                 + (f": {msgs[0].strip()[:200]}" if msgs and msgs[0] else ""))
            for node in h[pid].get("outputs", {}).values():
                for img in node.get("images", []):
                    q = urlencode({"filename": img["filename"],
                                   "subfolder": img.get("subfolder", ""),
                                   "type": img.get("type", "output")})
                    with urllib.request.urlopen(f"{url}/view?{q}", timeout=120) as r:
                        return r.read()
        time.sleep(1.5)
    raise ImageError(f"ComfyUI didn't finish within {timeout} s")


# ------------------------------------------------------------------ nano --
def gen_nano(prompt, key, model, timeout=90):
    """One image from Nano Banana. Returns PNG/JPEG bytes."""
    import base64
    import urllib.error
    import urllib.request
    body = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"],
                             "imageConfig": {"aspectRatio": "1:1"}},
    }).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        detail = _http_error_detail(e)
        if "api key" in detail.lower():
            raise ImageError(NANO_KEY_MSG) from e
        raise ImageError(f"Nano Banana: {detail}") from e
    except OSError as e:
        raise ImageError(f"Nano Banana is unreachable ({e})") from e
    for cand in resp.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            blob = part.get("inlineData", {}).get("data")
            if blob:
                return base64.b64decode(blob)
    raise ImageError("Nano Banana returned no image "
                     f"(finishReason: {(resp.get('candidates') or [{}])[0].get('finishReason')})")


# -------------------------------------------------------------- readiness --
_PROBLEM_KEYS = {"claude": ("Claude Code CLI", "resvg"), "comfyui": ("ComfyUI",),
                 "nano": ("Gemini", "Nano Banana")}


def readiness(cfg, backend):
    """(ok, error, fix) for drawing with `backend` right now — config.checks'
    own wording, so the 503 and the setup banner never disagree. Checks the
    backend asked for, which may not be the configured one."""
    probe = dict(cfg)
    probe["image_backend"] = backend
    c = config.checks(probe)
    if c["ready"]["pictures"]:
        return True, None, None
    problems = c.get("problems") or []
    for p in problems:
        if any(k in p["what"] for k in _PROBLEM_KEYS.get(backend, ())):
            return False, p["what"], p["fix"]
    if problems:
        return False, problems[0]["what"], problems[0]["fix"]
    return False, f"the {backend} picture backend isn't set up", "run ./install.sh"


# --------------------------------------------------------------- generate --
def normalize_backend(b):
    b = (b or "").strip().lower()
    return "comfyui" if b == "comfy" else b


def generate(pdir, subject, backend, style, count, cfg):
    """Draw `count` options in parallel into <pdir>/refs/.
    Returns (files, titles, used_backend, errors) — files are basenames in
    refs/, titles align with files (None when the backend gives none)."""
    backend = normalize_backend(backend)
    if backend not in BACKENDS:
        raise ValueError(f"unknown image backend {backend!r}")
    style = style if style in STYLES else "turnaround"
    count = max(1, min(int(count or 4), MAX_OPTIONS))
    slug = re.sub(r"[^a-z0-9]+", "_", subject.lower()).strip("_")[:32] or "idea"

    if backend == "claude":
        wait_s = CLAUDE_TIMEOUT_S

        def job(i):
            return claude_option(cfg, subject, style, TAKES[i % len(TAKES)])
    elif backend == "comfyui":
        url = config.comfy_url(cfg)
        if not url:
            return [], [], backend, ["ComfyUI is not answering — start it, or run "
                                     "scripts/setup_comfyui.sh"]
        models, _missing = config.comfy_model_choice(cfg, url)
        steps = config.get_path(cfg, "comfyui.steps") or 8
        prompt = raster_prompt(subject, style)
        # one queue: every option is submitted at once and waits its turn, so
        # the last one needs its own render time plus everyone ahead of it
        wait_s = 120 + 90 * count

        def job(i):
            return gen_comfy(prompt, url, models, steps, timeout=wait_s), None, None
    else:
        key = config.gemini_key(cfg)
        if not key:
            return [], [], backend, ["no Gemini API key for Nano Banana"]
        model = config.get_path(cfg, "nano.model") or "gemini-2.5-flash-image"
        prompt = raster_prompt(subject, style)
        wait_s = 90

        def job(i):
            return gen_nano(prompt, key, model), None, None

    results, errs = [None] * count, [None] * count

    def worker(i):
        try:
            results[i] = job(i)
        except ImageError as e:              # collect, don't die — partial results count
            errs[i] = str(e)
        except Exception as e:
            errs[i] = f"{backend}: {e}"

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(count)]
    for t in threads:
        t.start()
    # one shared deadline: joining each thread with its own full timeout let
    # four stuck options hold the request for four timeouts back to back
    deadline = time.monotonic() + wait_s + 30
    for t in threads:
        t.join(timeout=max(0.0, deadline - time.monotonic()))

    files, titles, errors = [], [], []
    for i, t in enumerate(threads):
        if t.is_alive():
            errors.append(f"option {i + 1} didn't finish in time")
            continue
        if errs[i]:
            errors.append(errs[i])
            continue
        if not results[i] or not results[i][0]:
            errors.append(f"option {i + 1} came back empty")
            continue
        blob, svg, title = results[i]
        data, ext = to_png(blob)
        path = save_unique(os.path.join(pdir, "refs"), f"gen_{slug}{ext}", data)
        vec = os.path.join(pdir, "vectors",
                           os.path.splitext(os.path.basename(path))[0] + ".svg")
        if svg:
            # same stem as the PNG; a stale one left by a picture deleted by
            # hand is simply replaced
            os.makedirs(os.path.dirname(vec), exist_ok=True)
            with open(vec, "w", encoding="utf-8") as f:
                f.write(svg)
        elif os.path.isfile(vec):
            # a raster picture reusing a deleted Claude picture's name must not
            # inherit its vectors — Make me 3D would build the old drawing.
            # Renamed aside, not deleted.
            stem = os.path.splitext(os.path.basename(vec))[0]
            os.replace(vec, unique_path(os.path.dirname(vec), stem + ".orphan.svg"))
        files.append(os.path.basename(path))
        titles.append(title)
    return files, titles, backend, errors
