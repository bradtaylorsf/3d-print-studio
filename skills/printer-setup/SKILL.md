# printer-setup — onboard a printer (or a new user of this repo)

Use this skill when someone sets up this repo for the first time, adds a printer, or says
"set up my printer" / "I have a <model>". It turns "I own printer X" into a researched,
maintained knowledge base the other skills build on. (This is the initiation flow for
anyone adopting this repo — it is deliberately printer-agnostic.)

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

## Step 3 — Write the knowledge base

```
printers/<model_slug>/
├── profile.md            hard specs + practical envelope + default material profile table
├── resources.md          index of forums/wikis/docs with what-each-is-for
├── common-problems.md    known issues for this model + fixes (seeded from research)
└── log.md                running memory: date, project, what worked, what didn't
```

Then update the repo's `CLAUDE.md` to point at the active printer profile so every future
session loads it. (In this repo, the Creality K2 profile lives directly in `CLAUDE.md` —
migrate it into `printers/creality_k2/` if a second printer ever appears.)

## Step 4 — Maintain the memory

After every notable print outcome (success worth repeating, failure diagnosed via
print-troubleshooting): append one line to `printers/<slug>/log.md` — date, project,
settings that mattered, verdict. When a problem recurs, promote it into
`common-problems.md` with the fix that worked. These files are the source of truth the
slicing and troubleshooting skills should read before advising.
