---
name: print-troubleshooting
description: >-
  Diagnose and fix FDM print problems and dial in print quality on the Creality K2 with PLA.
  Use whenever the user describes a failed or ugly print, asks "why did this fail", or wants tips
  to improve a result: poor bed adhesion / warping / not sticking, stringing / blobs, layer shifts,
  gaps or weak layers, rough overhangs, elephant's foot, clogs/under-extrusion, first-layer
  problems, or supports that won't come off. Trigger on: "failed print", "not sticking",
  "warping", "stringing", "layer shift", "clog", "rough", "why did this happen".
---

# K2 Print Troubleshooting & Tips (PLA)

Diagnose from the symptom, give the most likely cause first, then the fix. Settings reference
Creality Print 7.1.1.4472. Default material is PLA. When the user has a photo, look at it.

## First-layer & adhesion

| Symptom | Likely cause | Fix |
|---|---|---|
| Print won't stick / lifts | nozzle too high, dirty/cold bed | Re-run **auto bed leveling**; wash plate with dish soap (oils kill PLA adhesion); bed 60 °C; lower Z-offset slightly |
| First layer too thin/scratchy | Z-offset too low | Raise Z-offset in tiny steps |
| Corners curling up (warping) | cooling/draft, weak adhesion | Add a **brim** (5–8 mm); keep door closed to block drafts; do **not** crank chamber heat for PLA |
| Elephant's foot (squished base) | nozzle too low / bed too hot | Raise Z-offset slightly; enable elephant-foot compensation (~0.15 mm); bed 55 °C |
| Small/tall parts tip over | tiny footprint | Add a **brim** or a base (`stl-prep addbase`) |

PLA bed prep is mostly **cleanliness + correct Z-offset**. Most "bad printer" days are a greasy
plate. Recommend a soap-and-water wash before blaming settings.

## Surface quality

| Symptom | Likely cause | Fix |
|---|---|---|
| Stringing / wisps between parts | over-temp, retraction too low | Drop nozzle to 210–215 °C; ensure retraction ~0.8–1.0 mm; enable combing/"avoid travel" |
| Blobs / zits on surface | pressure at seam | Lower outer-wall speed; enable seam alignment / "scarf" seam; check for wet filament |
| Ghosting / ringing near corners | speed/accel too high | Lower acceleration and outer-wall speed; the K2's input shaping helps but isn't unlimited |
| Rough/ drooping overhangs | not enough cooling, angle too shallow | Fan 100%; slow overhang speed; add support below ~50° |
| Visible layer lines on figurine | layer height too coarse | Drop to 0.12–0.16 mm for detail areas |
| Wet-filament symptoms (popping, rough, weak) | moist PLA | Dry filament 4–6 h ~45–50 °C; store with desiccant |

## Structural / extrusion

| Symptom | Likely cause | Fix |
|---|---|---|
| Gaps between walls/infill, weak layers | under-extrusion | Check for partial clog; verify flow ~100%; raise temp 5 °C; confirm filament diameter |
| Layer shift (offset mid-print) | belt/obstruction/too fast | Reduce speed/accel; ensure gantry path clear; check belt tension; supports knocked the head |
| Clog / no extrusion | heat creep, debris, wet filament | Cold-pull/clean nozzle; **vent the enclosure on long PLA prints**; keep part cooling on |
| Splitting along layers (delamination) | temp too low / cooling too high for the geometry | Raise nozzle 5–10 °C; for thin tall walls reduce fan slightly on first few mm |

## Supports won't come off / scar the surface

Hand off to the **k2-supports** skill. Quick fixes: increase **top Z-gap** to 0.25–0.3 mm, switch
to **tree** supports, reduce interface density, and reorient so the supported area isn't a
cosmetic face.

## K2 specifics

- **Chamber camera (720p)**: use the live feed and time-lapse to catch a bad first layer or an
  early failure; check on it rather than assuming it caught a problem for you.
- **Passive enclosure (no chamber heater)**: good for PLA — keep part cooling at 100% and **vent
  the door/top on long PLA prints** to avoid heat-creep clogs. Large ABS/ASA prints warp more here
  than on the heated K2 Plus/Pro, so add a brim and block drafts.
- **CFS multi-color**: stringing and color bleed usually mean purge/flush volume is too low — raise
  flush volume for light-after-dark transitions and keep a prime tower.
- **Auto bed leveling**: re-run after moving the printer, swapping the plate, or any first-layer
  trouble.

## Diagnostic method

1. Ask for or look at a **photo** and the **layer/height** where it failed.
2. Identify the **single most likely cause** (don't change five things at once).
3. Give **one concrete change** + the value, then a fallback if that doesn't resolve it.
4. If it's a recurring model, suggest a **mesh/orientation fix** (stl-prep) rather than only slicer
   tweaks.
