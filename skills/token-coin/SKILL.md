---
name: token-coin
description: >-
  A child names a thing and it becomes a printable 28 mm token: a multi-colour snap-in coin
  traced from a picture in about a second (studio/tools/make_coin.py, the studio's 🪙 button),
  or a one-colour chip with a print-safety report (studio/tools/make_chip.py), plus how to get
  a picture that traces well and how to slice the colour change. Use for "make me a dinosaur
  coin", "can I have a shark one", "make my coin", a photo of a child's drawing, a coin that
  traced badly, or "the kids are picking their tokens".
---

# token-coin — a child picks a thing, and it becomes a printable token

Use this skill when someone wants a **new token coin or chip** — "make me a dinosaur one",
"can I have a shark", "I want a rocket" — or a grown-up says "the kids are picking their
tokens". Also use it for a photo of a drawing on paper, and when a coin from the studio's
🪙 button came out wrong.

A token is a 28 mm round, chamfered chip with a picture raised on top. A family can design
a **token board** for them to drop into — a tray with round sockets; no board generator
ships, but `SOCKET_*` and `socket_cutter()` in `chip_geometry.py` give the exact socket — or
just collect them in a jar. Every chip must fit the same socket, so **never invent chip
dimensions** — `studio/tools/chip_geometry.py` is the single source of truth and both tools
import it.
Changing `CHIP_D`, `FACE` or `EMBOSS` breaks every chip already printed.

Paths below are relative to the repo root. `<projects>` is the studio's projects directory
(`projects/` unless `projects_dir` in `studio.config.json` says otherwise); the picture
library is `<projects>/library/`.

## THE COIN — the default path (seconds, not minutes)

`studio/tools/make_coin.py` turns any picture into a **multi-colour snap-in coin**
deterministically — cut the subject off the background, pull out dark linework first, k-means
the remaining colours into up to 4 flat regions, trace each region, extrude each as its own
part on a coin body. **No AI in the loop. ~1 second.** This replaces the 5–15 min
Make-me-3D build for everyday tokens; keep Make-me-3D for full 3D toys.

```bash
.venv/bin/python studio/tools/make_coin.py <image> --name dragon --out <projects>/<proj>
```

Or through the studio — what the kids use, at `http://localhost:8765/?kid=1`:
**🎤 Tell me!** (or type) → the studio draws **4 sticker-style pictures** → the child taps
one → **🪙 Make my coin!** → the coin appears with the picture's own colours → they repaint
any part with the colour dots → **🖨 Send to 3D printer** opens the slicer. The server
endpoint is `POST /api/projects/<n>/coin {"image": "<refs file>"}` — it creates (or, on a
redo, reuses) a per-creation project named `<image>_coin` and runs the script with the
repo's own `.venv/bin/python`.

Output (in the project directory): `parts/coin_body.stl` + `parts/coin_c1..c4.stl` +
`parts/parts.json` (colours lifted from the image), `model.stl`,
`final/token_coin_<name>_28mm.stl`. All watertight or the script is broken — it
open-close buffers each region and fills holes precisely because clipped slivers used to
leak.

**Best input = flat sticker art**: 3–4 flat colours, no shading (the generate endpoint's
`style: "sticker"` produces exactly this; kid mode uses it automatically). Photos and
shaded art will cluster noisily — regenerate rather than fight it.

**Thin lines survive on purpose.** Dark linework (a web pattern, whiskers, a smile) is
extracted *before* colour clustering and grown to printable width before any colour region
claims space. Only dark lines count (luminance under `DARK_T`); pale outlines are clustered
as colour like everything else and can break up into dots. Regenerate with bold dark
outlines rather than tuning the constant.

**CFS slicing a coin:** up to 4 filaments — body + 3 regions is the sweet spot. All
regions live in one Z band (6.05 → 7.25 mm), so colour changes are per-layer with a
small purge tower; the parts are tiny, cost is minutes. Assign slots per part colour in
the slicer from the parts.

## The rule that makes this work

The chip's flat face and a board's flat face are **the same height, 6.05 mm**. Every
raised feature in the whole system starts at exactly that Z and nowhere else, which is
what makes a two-colour chip **one filament change** instead of one per part. Anything
you add must keep that contract.

---

## Step 1 — Ask the child for one thing, and keep it simple

You want a single object, not a scene. "A T-rex" works. "A T-rex in a jungle eating a
leaf at sunset" does not — it comes back as a picture, and a picture makes an unreadable
28 mm chip.

If they name something spindly (a spider, a stick figure, a firework), say it will come
out chunky, and offer the chunky version by name. Better to set the expectation than to
hand them a blob.

## Step 2 — Get the pictures

Use the studio's generate endpoint — it writes the options into the picture library:

```bash
curl -s -X POST http://127.0.0.1:8765/api/projects/library/generate \
     -H 'Content-Type: application/json' \
     -d '{"subject": "a T-rex", "style": "sticker"}'
```

It answers with `count` options (default 4, `options` in the config) as
`refs/gen_<slug>.png`, `gen_<slug>_2.png`, … plus a `reply` sentence and, from the Claude
backend, a `title` per option. Look at them (Read the PNGs), pick the one with the
chunkiest, flattest subject, then make its coin:

```bash
curl -s -X POST http://127.0.0.1:8765/api/projects/library/coin \
     -H 'Content-Type: application/json' -d '{"image": "gen_a_t_rex_2.png"}'
```

`style: "sticker"` asks for flat colours (what `make_coin.py` wants); `style: "chip"` asks
for one bold solid silhouette instead — what the one-colour `make_chip.py` likes best,
though a sticker picture works for a chip too.

Which backend draws is `image_backend` in `studio.config.json` (`auto` = Nano Banana if a
Gemini key exists, else a running ComfyUI, else Claude). A 503 with `"setup": true` means
that backend isn't ready — `scripts/doctor.py` says why.

- **Claude (Opus 5.5)** — the user's own Claude Code CLI, headless, one call per option.
  It draws an SVG; the studio sanitises it, renders the PNG, and keeps the vector in
  `library/vectors/<stem>.svg`. Flat fills by construction, so it traces cleanly.
  ~20–60 s for 4.
- **ComfyUI** — local Z-Image Turbo, free per picture. Two things that will waste your
  time if you don't know them:
  1. **comfy-cli can report `running: false` while a ComfyUI is up** — a ComfyUI started
     by hand on another port is invisible to it. The studio uses `comfyui.url`, or probes
     127.0.0.1 ports 8188/8000/8189 itself. Never conclude ComfyUI is down from comfy-cli
     alone — curl `/system_stats` on the port.
  2. **`object_info` is cached at startup.** A model added after ComfyUI launched will not
     appear in the node's dropdown list until you re-request `object_info` (or restart
     it). That is what makes a model file look missing when it is on disk.
- **Nano Banana** — Google's `gemini-2.5-flash-image`; needs `GEMINI_API_KEY` or the key
  file in `nano.key_file`.

### The ComfyUI stack

Z-Image Turbo, lifted from ComfyUI's own bundled `image_z_image_turbo.json`:
`UNETLoader z_image_turbo_bf16` · `CLIPLoader qwen_3_4b type=lumina2` ·
`VAELoader z_image_ae` · `res_multistep`/`simple`, 8 steps, **cfg 1**, AuraFlow shift 3.
`scripts/setup_comfyui.sh` installs ComfyUI and downloads exactly these three files
(`--models-only` to fetch just the models into an existing ComfyUI).

> ⚠️ **cfg = 1 means the negative is zeroed out, so a negative prompt does NOTHING.**
> Every constraint has to be phrased positively — which is why the built-in prompt says
> *"one single filled silhouette"* rather than *"no line art"*. Do not add a negative
> prompt and assume it worked.

The prompts live in `studio/imagegen.py`: `STICKER_PROMPT`, `CHIP_PROMPT` and
`TURNAROUND_PROMPT` for ComfyUI / Nano Banana (`{subject}` is the only part that changes),
and `claude_prompt()`, which builds the Claude backend's SVG prompt per option. If you need
to hand one to a different image model, that is the text.

**A photo of a drawing works too** — shoot it flat in even light, dark marker on white
paper, drop it on the studio page (it lands in the project's `refs/`), and skip straight
to the coin or to Step 3. On a flat-colour background the tracer removes whatever matches
the border colour (so light bellies and eyes on a light background survive — they only
need to differ from the exact background colour); on an uneven background it falls back
to a threshold whose polarity is read from the border pixels, so either way round is
fine. Sticker-style drop shadows are detected and dropped.

## Step 3 — Make a one-colour chip (when a coin is not wanted)

```bash
.venv/bin/python studio/tools/make_chip.py \
    <projects>/library/refs/<image>.png --name dinosaur --fast --copies 4 \
    --out <projects>/<proj>
```

| Flag | Use |
|---|---|
| `--name` | what the chip is called in the filename |
| `--out` | the project directory to write into (default: the image's project, the parent of its `refs/`) |
| `--fast` | 0.28 mm layers, 26 layers instead of 36. **Chip-only plates only** — never on a plate that also has a board |
| `--copies N` | default 2 (one to keep, one to pocket). 4 is barely slower than 1 — the colour change is shared |
| `--thicken MM` | force extra growth when auto isn't enough |
| `--invert` | if the subject and background came out swapped (`make_coin.py` takes it too) |
| `--keep N` | how many separate pieces to allow (default 6) |

## Step 4 — READ THE REPORT. This is the step people skip

```
  sub-nozzle area 90.8 %  ->  0.1 %   (tolerance 3 %)
  face coverage   38 %
  PRINT-SAFE      YES
```

- **`PRINT-SAFE NO`** → do not print it. Regenerate with a chunkier subject, or pass
  `--thicken 0.4`. It will print as a smear otherwise.
- **`sub-nozzle area`** — how much of the art is narrower than the nozzle can lay down.
  Under 3 % is tips, which are fine. The tool grows thin limbs automatically up to
  1.2 mm; if it hit that cap and is still over, the art is too spindly for 28 mm.
- **`face coverage`** — aim for **35–60 %**. Under 15 % looks lost on the chip; over 75 %
  is a white disc with black scratches, and it burns white filament.
- **`pieces dropped`** — specks removed. A few is good (noise). Dozens means the image
  was messy; regenerate rather than print it.

Then **look at `previews/token_chip_<name>.png`** — source image beside the chip. If you
cannot tell what it is at that size, neither can a five-year-old.

A coin's report (the studio returns its tail as `report`) is shorter — the colour regions,
the size, watertight per part, and the relief band with its colour-change layer. Open the
coin in the studio and look at it the same way: if you can't tell what it is, regenerate.

## Step 5 — Slice it

PLA, 0.28 mm layers (or 0.20 without `--fast`), 3 walls, 15 % gyroid, **no supports**,
brim off for chips (the chamfered edge sits fine on PEI), 100 % cooling. On the default
Creality K2 the k2-slicing skill has the rest; another printer's numbers are in its
`printers/<slug>/profile.md`.

**The colour change is the whole job.** The report prints the layer:

```
  colour change   after layer 22  (Z 6.13 mm)   exact
```

Body colour below, art colour above. Two ways to do it:

- **Manual change (recommended for chips).** One pause at that layer, swap the spool,
  resume. No prime tower, no purge waste, ~30 seconds of attention. On a plate this
  small the tower would out-weigh the parts.
- **CFS / AMS.** Assign the two colours to two slots with a height-based change.
  Convenient, but note **dark → light is the expensive purge direction** — light after
  dark needs a lot of flushing. Print 4+ copies so the flush amortises over something.

Four chips at 0.28 mm is roughly 10–13 minutes. The slicer gives the real number.

## What not to do

- Don't change `CHIP_D`, `FACE`, `EMBOSS` or `SOCKET_*` to make a picture fit. Change the
  picture.
- Don't use `--fast` on a plate that also carries a board — different face height, and
  the single colour change silently becomes two.
- Don't print a `PRINT-SAFE NO` chip to "see how it comes out". It comes out badly, and
  the child watched you print it.
- Don't put words on a chip. These are wordless by design — a picture a child chose, not
  a label.
