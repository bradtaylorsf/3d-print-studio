---
name: printer-setup
description: >-
  Onboard a printer (or a new user of this repo): interview, research the machine, write the
  printers/<slug>/ knowledge base (profile, resources index, common problems, running log) and
  point the studio at it by setting the printer keys in studio.config.json (bed size, margin,
  name, slicer). Use when someone sets up this repo with a printer that isn't the shipped
  Creality K2, adds a printer, or says "set up my printer" / "I have a <model>" / "my bed is
  bigger".
---

# printer-setup — onboard a printer (or a new user of this repo)

Use this skill when someone sets up this repo for the first time, adds a printer, or says
"set up my printer" / "I have a <model>". It turns "I own printer X" into a researched,
maintained knowledge base the other skills build on, and points the studio at it. (This is
the initiation flow for anyone adopting this repo — it is deliberately printer-agnostic.)

The repo ships tuned for a **Creality K2** with **Creality Print**: that is the default in
`studio/config.py`, and `printers/creality-k2/profile.md` is the worked example of what this
skill produces. The K2-named skills (k2-slicing, k2-supports, print-troubleshooting's error
codes) keep their K2 detail; on another printer they defer to that printer's
`profile.md` for numbers.

## Step 1 — Interview (one batched message)

Ask, with sensible defaults offered:
1. **Printer make/model** (and count, if a farm) — plus any mods (hardened nozzle, etc.).
2. **Slicer + version** — menu paths in skills are pinned to a version.
3. **Materials they actually run** (default assumption: PLA) and multi-material hardware
   (AMS/CFS/MMU) if any.
4. **What they print** — figurines / functional / both. Sets default profiles.

## Step 2 — Research the printer (web)

For each printer, gather and verify from at least two sources:
- Hard specs: build volume, nozzle temps, bed temps, enclosure (active/passive/none),
  motion system, direct drive vs bowden, max speeds actually usable.
- Community knowledge index: official wiki/docs URL, the subreddit, the main forum threads,
  a note on what each is good for. Record what could NOT be found too.
- Known common problems for this model (search "<model> common problems", "<model>
  first layer", etc.) with the accepted fixes.

Watch for sibling models with the same name and different beds (the K2 is 260³, the
K2 Pro 300³, the K2 Plus 350³). Confirm against the bed size the user's slicer shows for
their printer profile — that is the number that matters.

## Step 3 — Write the knowledge base

The slug is the printer name lowercased with hyphens (`Creality K2` → `creality-k2`,
`Bambu Lab P1S` → `bambu-lab-p1s`).

```
printers/<slug>/
├── profile.md            hard specs + practical envelope + default material profile table
├── resources.md          index of forums/wikis/docs with what-each-is-for
├── common-problems.md    known issues for this model + fixes (seeded from research)
└── log.md                running memory: date, project, what worked, what didn't (personal)
```

Model `profile.md` on `printers/creality-k2/profile.md`: a facts table, the practical design
envelope, a default PLA profile, material notes, and the `studio.config.json` values for this
printer. Keep it generic — no dates of what happened to *this* machine; those go in `log.md`.

## Step 4 — Point the studio at it

Set the printer keys so the studio's bed grid, envelope box, "fits" badge, the Make-me-3D
prompt, `meshtools.py info` and the 🖨 button all use the new machine:

```bash
.venv/bin/python scripts/configure.py set \
    printer.name "Bambu Lab P1S" \
    printer.bed_mm '[256,256,256]' \
    printer.margin_mm 5 \
    printer.slicer "Bambu Studio"
.venv/bin/python scripts/doctor.py          # confirms the slicer is found
```

- `printer.bed_mm` is `[X, Y, Z]` in mm; the design envelope is the bed minus
  `printer.margin_mm` on every axis (255³ on a K2).
- `printer.slicer` is the macOS app name (`open -a "<name>"` must work), or a command / path
  on Linux. Check it with `doctor.py`; if it says not found, fix the name before moving on.
- The server re-reads `studio.config.json` when it changes — no restart needed.

Then make sure `AGENTS.md`'s printer section still reads true (it takes the printer from
`studio.config.json` + `printers/<slug>/profile.md`; edit it only if it names a printer
directly).

## Step 5 — Maintain the memory

After every notable print outcome (success worth repeating, failure diagnosed via
print-troubleshooting): append one line to `printers/<slug>/log.md` — date, project,
settings that mattered, verdict. When a problem recurs, promote it into
`common-problems.md` with the fix that worked — generically worded, since that file is
shared. These files are the source of truth the slicing and troubleshooting skills should
read before advising.

`log.md` is personal: the public repo's `.gitignore` excludes `printers/*/log.md`, and the
export/privacy check refuses to ship one. Keep names, dates and purchases there, not in
`profile.md` or the skills.
