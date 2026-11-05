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

The general tables apply to any FDM printer; the error-code sections are specific to the
Creality K2, the printer this repo ships tuned for. Before advising, read the active
printer's `printers/<slug>/profile.md` and, if the user keeps one, its `log.md` — a
problem that happened before is the most likely cause again. After a fix works, append a
line to that `log.md` (see printer-setup).

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

## "Extruder may be clogged" (FO2845): the K2 clog alarm

**How it detects a clog:** the **CFS buffer** on the back of the head senses filament tension.
When the extruder stops pulling filament, the buffer doesn't move and the printer reports a
clog. This means the alarm also fires for problems **upstream of the nozzle**: spool drag,
PTFE friction, or the buffer itself. A clear nozzle does not rule the alarm out. It most
often fires during the start-of-print purge or a CFS flush.

Work top-down and stop at the first failure:

1. **Hotend test** (Creality's own check): heat to 220 °C, remove the filament, and push a
   short piece in by hand. If it won't go in or feels stiff, the hotend is clogged. Use the
   hot-needle method (heat the needle, insert it into the heat break, let it cool 30 s, pull)
   or a cold pull. If that fails, replace the integrated nozzle; it's cheap and swaps in
   minutes. **The K2/K2 Pro nozzle has the heat break built in**, so if the needle stops
   where the finned heatsink meets the heater cylinder, the plug is inside the nozzle's own
   heat break. Fix: retract the filament, lower the bed, heat to 220 °C, and unscrew the nozzle
   from below with a **6 mm socket** (counter-clockwise; hot, so mind the burns). From the
   front, the round black silicone-covered part with copper wires looks like "the nozzle"
   but it's the **heater**. Leave the silicone cover and the wires alone. The hex is only
   the small tip poking out of the **bottom** of that part, so look from underneath. Use a
   slim nut driver, because a chunky socket won't fit up into the cover. If the tip is caked
   in plastic, scrape it clean at temperature first. **Getting the nozzle out usually tears
   the silicone cover, so order both parts together.** Replacement nozzle: Creality
   "Unicorn" quick-swap nozzle, listed for the K2, K2 Plus and Hi
   ([Creality store](https://store.creality.com/products/unicorn-k2-plus-quick-swap-nozzle-kit)).
   Cover: Creality's official K2/K2 Pro/K2 Plus silicone socks (sold in multi-packs).
   Keep a spare of each on hand. Fitting the new one: finger-start it cold, tighten it hot
   at 220 °C, and fit the cover afterwards — a nut driver may not fit through the cover's
   hole.
   **After a nozzle swap, TE2564 "nozzle is not heating as expected"** almost always means the
   heater's **heating-wire or thermistor plug** was knocked loose, or its thin copper wires
   were nicked while tearing the cover or twisting the nozzle. To check:
   - Power off and unplug.
   - Reseat both plugs.
   - Trace the wires for breaks, and check the round heater didn't rotate and twist them.
   - Power on and set the nozzle to 200 °C.
   If it still won't climb, the heater (hotend kit) is damaged
   ([TE2564](https://wiki.creality.com/en/printers-general-documents/TE2564),
   [hotend kit](https://wiki.creality.com/en/k2-flagship-series/k2-pro/replace-hotend-kit)).
   Hold the round heater still with pliers while turning the nozzle so the wires can't twist. Clear it or
   fit a new one with thermal paste on the heat break and threads. Then Extrude to test and
   re-run Input Shaping + Auto Leveling. No need to touch the two screws on the heatsink
   ([K2](https://wiki.creality.com/en/k2-flagship-series/k2/replace-nozzle),
   [K2 Pro](https://wiki.creality.com/en/k2-flagship-series/k2-pro/replace-nozzle)).
2. **Extruder**: a "cleaned" printer often still has a **curled or broken filament stub above
   the gears** or **ground dust in the gear teeth**. Open the extruder, cut out anything
   swollen, brush the three gears, and check them for chipped teeth (front housing kit SKU
   4001020081). Also check that the **cutter isn't blocking the outlet** and that the
   guide piece is present.
3. **Extruder cooling fan**: heat to 100 °C and confirm it spins. A dead fan means heat creep
   and a real re-clog on every print.
4. **Chamber temp for PLA must stay ≤ 37 °C.** On a K2 Pro/Plus, make sure the filament
   profile isn't calling for chamber heat. On any K2, vent the enclosure on long PLA prints.
5. **Buffer (false alarms)**: the blue light should be on. Reseat the buffer ↔ CFS cable and
   every PTFE connection. The fix that worked most often on the Creality forum was a loose
   buffer-to-CFS connector. Open the buffer and clean the optical sensor window with a
   swab. Buffer errors FB2864/FB2846 point here too. If the **CFS's four lights sweep red in
   sequence**, the printer can't see the CFS at all. That's the same communication chain, so
   fix it first. It's normal only during a firmware update or reboot.
6. **Upstream drag**: spin the spool by hand, check that the CFS shaft turns freely, and
   look for kinked or tight PTFE runs. A buffer stuck at the **full right limit** means the
   extruder can't pull against drag. A buffer stuck at the **middle limit** means the
   extruder or nozzle.
7. **Filament**: dry it and check the diameter. Wet or out-of-round PLA both trigger this.

Sources: [Creality wiki FO2845](https://wiki.creality.com/en/printers-general-documents/FO2845),
[K2 extruder jam](https://wiki.creality.com/en/k2-flagship-series/k2/extruder-jammed-filament),
[forum: clog error with nothing inside](https://forum.creality.com/t/creality-k2-nozzle-clogging-issue-when-nothing-is-inside/39504).

## TE2762 "extruder leveling sensor damaged / wiping module fallen off" + TE2766 "failed to return to XY, can't clean nozzle"

The two can appear together — for example after a part comes loose and gets dragged around
the bed, or after the plate has been washed and refitted. **TE2762** is the **strain gauge**:
the toolhead sensor that uses the nozzle itself to find the bed. It is also raised when the
**nozzle wiper** has come off or been bent, because then the nozzle hits the gauge while
wiping. **TE2766** means the XY homing before that wipe failed. Creality doesn't link the two
codes. Work top-down:

1. Power off and let the nozzle cool. Remove every loose part, string and blob from the bed,
   the chamber floor and the back wall, and pick any blob off the nozzle tip.
2. Check the **wiper**. It's at the back wall on the black purge-chute box; that location is
   read from Creality's photos, not stated in text. Its **2 screws** should be tight and the
   **metal dome** should spring back freely. The silicone pad should be present. The nozzle
   should only *lightly* scrape the dome; the 4-screw base adjusts that. Bent dome → replace
   the module (SKU 4004010292). Worn pad → replace just the pad.
3. Power off: slide the head by hand across X/Y to feel for stiff spots, and check the drag
   chain hasn't popped off at the extruder end. Don't unplug cables while it's powered.
4. Power on: Axis/Temp → centre home (XY), then Z home. Keep a hand near the switch the first
   time, because owners report the bed being driven into the nozzle on a bad gauge reading.
   Tick Print Calibration (auto-leveling) on the next print.
5. Still erroring: send Creality support a video **before buying a strain gauge** (SKU
   4001010038). Owners report gauge swaps that didn't fix it and the printhead cable as the
   other culprit. Don't run the Fluidd servo recalibration or roll back firmware unless
   support says to.

Sources: [TE2762](https://wiki.creality.com/en/printers-general-documents/TE2762),
[TE2766](https://wiki.creality.com/en/printers-general-documents/TE2766),
[K2 nozzle wiper](https://wiki.creality.com/en/k2-flagship-series/k2/nozzle-wiper),
[K2 maintenance tips](https://wiki.creality.com/en/k2-flagship-series/k2/maintenance-tips),
[forum: K2 Pro multi-error thread](https://forum.creality.com/t/k2-pro-so-many-errors-i-dont-know-where-to-start/52331).

## Bigger nozzles (0.6 / 0.8): when they help

The "Unicorn K2P" kit (SKU 4008030075: 2×0.4, 1×0.6, 1×0.8) fits the base K2. Creality's
base-K2 nozzle page links to it. **A bigger nozzle does not raise the melt limit.** Creality
Print caps the same PLA at the same mm³/s at 0.4, 0.6 and 0.8 (CR-PLA 18, Hyper PLA 23, on
K2 Plus presets). So a print that is already flow-limited gains nothing from a swap, like
large bodies with thick walls printed at the cap. In the time model, the 0.6 came out the
same at equal wall thickness, and the 0.8 came out slower. It helps only **speed-limited**
jobs (small, slow detailed prints that never reach the cap — a detailed figurine averaged
~5 mm³/s). It costs detail and needs a re-slice on the "Creality K2 0.6/0.8 nozzle" printer
preset; there's no Generic PLA preset at those sizes. Swap it hot per the
[K2 replace-nozzle page](https://wiki.creality.com/en/k2-flagship-series/k2/replace-nozzle):
6 mm socket, thermal grease on the tube, snug not cranked. Then run Self-Check (Input Shaping
+ Auto Leveling). Have a spare silicone sock ready first.

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
- **CFS front lights** ([wiki](https://wiki.creality.com/en/cfs/status-indicator-explaination)):

  | Lights | Meaning |
  |---|---|
  | White steady | Loaded, idle |
  | White breathing | Printing |
  | 4 white in sequence | Connected, no filament loaded |
  | **4 red in sequence** | **CFS not communicating** with the printer |
  | Red steady | Hub sees filament, slot doesn't |
  | Red single flash | Filament in the slot but not in the hub (load failed) |
  | Red double flash | Load/unload failed |
  | Red breathing | Slot empty or filament ran out mid-print |

- **After any firmware update**: the printer force-updates the CFS if its firmware is older, so
  expect the red sweep until both finish. Then retract filament and run Settings → Detecting
  options → Input Shaping + Auto Leveling before printing.

## Diagnostic method

1. Ask for or look at a **photo** and the **layer/height** where it failed.
2. Identify the **single most likely cause** (don't change five things at once).
3. Give **one concrete change** + the value, then a fallback if that doesn't resolve it.
4. If it's a recurring model, suggest a **mesh/orientation fix** (stl-prep) rather than only slicer
   tweaks.
