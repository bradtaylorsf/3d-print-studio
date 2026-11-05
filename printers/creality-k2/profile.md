# Creality K2 — printer profile

The printer this repo ships tuned for: the base **Creality K2 / K2 Combo** (CoreXY, fully
enclosed, passive enclosure, CFS multi-colour) sliced in **Creality Print 7.1.1.4472**, with
**PLA** as the default material. The skills (k2-slicing, k2-supports, print-troubleshooting,
stl-prep) and the studio's defaults in `studio/config.py` all assume this file. For another
printer, run the printer-setup skill: it writes `printers/<slug>/profile.md` next to this one
and points `studio.config.json` at it.

## Studio settings for this printer

These are the defaults, so a fresh `studio.config.json` already matches:

| Key | Value | What it drives |
|---|---|---|
| `printer.name` | `"Creality K2"` | the "fits …" badge, the Make-me-3D prompt |
| `printer.bed_mm` | `[260, 260, 260]` | the viewer's bed grid |
| `printer.margin_mm` | `5` | design envelope = bed − margin = **255³** (badge, envelope box, `meshtools.py info`) |
| `printer.slicer` | `"Creality Print"` | the app the 🖨 button opens |

```bash
.venv/bin/python scripts/configure.py set printer.name "Creality K2" \
    printer.bed_mm '[260,260,260]' printer.margin_mm 5 printer.slicer "Creality Print"
```

## The machine

| Spec | Value |
|---|---|
| Motion system | CoreXY, fully enclosed |
| Build volume | **260 × 260 × 260 mm** (the K2 — not the K2 Pro or K2 Plus; see below) |
| Nozzle | 0.4 mm (default), all-metal quick-change, max **300 °C**; the nozzle has the heat break built in |
| Heated bed | PEI-coated flexible steel, up to **100 °C** |
| Chamber | **Passive enclosure (no active chamber heater)** |
| Max speed / accel | up to 600 mm/s / 20,000 mm/s² (real prints run far lower) |
| Extruder | Dual-gear direct drive, all-metal |
| Camera | Single 720p chamber camera (monitoring / time-lapse) |
| Multi-color | **CFS** unit (Combo): 4 filaments per CFS, up to 4 CFS = 16 channels; a buffer on the back of the head senses filament tension (and raises the clog alarm) |
| Bed probing | strain gauge in the toolhead (the nozzle finds the bed), plus a nozzle wiper at the back |

**Which K2 is it?** Creality's comparison gives the base K2 a 260³ bed, a passive chamber,
one chamber camera and a 100 °C bed. The **K2 Pro** is 300³ with an active 60 °C chamber
heater and a second camera; the **K2 Plus** is 350³, also actively heated. The bed size
Creality Print shows in your printer profile settles it — a plate that fits a Pro but comes
up "too big" on yours is the tell. If yours is a Pro or Plus, set `printer.bed_mm` to match
and treat the chamber notes below as optional (the heater makes ABS/ASA easier).

**Practical envelope for design/orientation:** keep parts inside **255 × 255 × 255 mm** to
leave clearance. For first prints of a new model, prefer the **center** of the bed.

**Firmware:** the changelog is on Creality Cloud → Downloads → 3D Printer Firmware →
Flagship Series → **K2** tab; hover "Description" on a version. Release notes are thin, so
read them before blaming or crediting firmware for a behaviour change. After any update the
printer force-updates an older CFS (expect the CFS's four lights to sweep red until both
finish), then run Input Shaping + Auto Leveling before printing.

## Default print profile (PLA)

Safe **starting points**, not gospel — the baseline an agent proposes, then tunes per model.
State the chosen numbers whenever a file is prepped. k2-slicing has the per-profile tables
(figurine / functional / large / CFS) and the Creality Print specifics.

| Setting | Value (PLA) | Notes |
|---|---|---|
| Nozzle temp | 215–220 °C | 220 first layer is fine |
| Bed temp | 60 °C | 55–60 °C |
| Chamber | Passive — vent for PLA | The K2 enclosure isn't actively heated; for long PLA prints crack the door/top so trapped heat doesn't cause heat-creep clogs. Keep it ≤ 37 °C for PLA |
| Layer height | **0.20 mm** general, **0.12–0.16 mm** for figurine detail | 0.28 mm for fast/draft |
| First layer height | 0.25 mm | better adhesion |
| Walls / perimeters | 3 (figurines), 4 (functional) | |
| Top/bottom layers | 4 / 4 (≈0.8 mm) | |
| Infill | 10–15% (figurines), 25–40% (functional) | Gyroid or grid |
| Print speed | 150–250 mm/s typical | Slow detailed areas; the K2 can go faster but quality drops |
| Outer wall speed | 60–120 mm/s | Slower = cleaner surface |
| Cooling fan | 100% (after layer 2–3) | PLA loves cooling |
| Retraction | ~0.5–1.0 mm (direct drive) | Keep low; direct drive needs little |
| Build plate adhesion | Brim for tall/small-footprint; skirt otherwise | Stock K2 process presets use `skirt_loops 0` |
| Build plate | Smooth/textured PEI; PLA releases best cooled | Wash with dish soap when adhesion drops |

**Material reality check:** the passive enclosure suits PLA fine — keep cooling high and
vent the enclosure on long prints to avoid heat creep. For PETG/ABS/ASA/TPU, adjust temps and
cooling per material; the passive enclosure makes large ABS/ASA prints more warp-prone than
on the actively heated K2 Pro/Plus, so add a brim and block drafts.

**Bigger nozzles:** the quick-swap 0.6 / 0.8 nozzles fit, but Creality Print caps a given PLA
at the same mm³/s at every size, so a swap only speeds up jobs that never reach that cap.
Details in print-troubleshooting.

## Where the rest lives

- Slicing, CFS colour assignment, Creality Print 3MF quirks → **k2-slicing**
- Supports → **k2-supports**
- Error codes (FO2845 clog alarm, TE2564, TE2762/TE2766), CFS light meanings → **print-troubleshooting**
- Mesh fit checks against the 255³ envelope → **stl-prep** (`meshtools.py info`)
- Official docs: the Creality wiki's K2 Flagship Series section, e.g.
  [K2 maintenance tips](https://wiki.creality.com/en/k2-flagship-series/k2/maintenance-tips)
  and [replace the nozzle](https://wiki.creality.com/en/k2-flagship-series/k2/replace-nozzle)
- Your own history with this machine → `log.md` here (personal; not part of the public repo)
