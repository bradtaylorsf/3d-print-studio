---
name: k2-slicing
description: >-
  Slice and configure prints for the Creality K2 in Creality Print v7.1.1.4472.
  Use whenever the user wants slice settings, a print profile, layer height / speed / temp /
  infill recommendations, a slicing plan, estimated print time, or a multi-color CFS setup.
  Covers PLA defaults, figurine vs functional vs large-part profiles, and the CFS multi-color
  workflow. The K2 is the repo's shipped default printer; for another printer, read its
  printers/<slug>/profile.md first. Trigger on: "slice", "settings", "profile", "how do I print
  this", "layer height", "infill", "multi-color", "CFS", "Creality Print".
---

# K2 Slicing (Creality Print 7.1.1.4472)

Goal: turn a print-ready mesh into the **right settings** for the K2, and explain the slice
plan in plain language. Default material is **PLA**. Build volume is **260×260×260 mm**
(the base K2 / K2 Combo, not the 300³ K2 Pro or 350³ K2 Plus; design to ≤255³ for clearance).

The Creality K2 + Creality Print is the printer this repo ships tuned for. The live numbers
are in `studio.config.json` (`printer.name`, `printer.bed_mm`, `printer.margin_mm`,
`printer.slicer`) and the machine's facts in `printers/creality-k2/profile.md`. **On any other
printer**, read `printers/<slug>/profile.md` (run the printer-setup skill if it doesn't
exist) and use its numbers; the method below still applies, but menu names and preset keys
are Creality Print's.

## Step 1 — Classify the print

Pick the profile that matches the model. This drives every other setting.

| Profile | Use for | Priorities |
|---|---|---|
| **Detail / figurine** | busts, miniatures, decor | fine layers, clean walls, supports |
| **Standard / functional** | brackets, fixtures, mechanical | strength, dimensional accuracy |
| **Large / display** | big single pieces near full bed | reliability, no warping, time |
| **Multi-color (CFS)** | anything using the CFS unit | clean color changes, purge control |

## Step 2 — Core PLA settings by profile

Start here, then tune. Always restate the chosen numbers to the user.

| Setting | Figurine | Functional | Large/Display |
|---|---|---|---|
| Layer height | 0.12–0.16 mm | 0.20 mm | 0.20–0.28 mm |
| First layer | 0.25 mm | 0.25 mm | 0.25 mm |
| Walls/perimeters | 3 | 4 | 3 |
| Top / bottom layers | 4 / 4 | 5 / 4 | 4 / 4 |
| Infill | 10–15% gyroid | 25–40% grid/gyroid | 10% gyroid |
| Nozzle temp | 215–220 °C | 215–220 °C | 215–220 °C |
| Bed temp | 60 °C | 60 °C | 60 °C |
| Outer wall speed | 60–100 mm/s | 100–120 mm/s | 100–150 mm/s |
| Inner/infill speed | 150–250 mm/s | 200–250 mm/s | 200–300 mm/s |
| Cooling fan | 100% | 100% | 100% |
| Adhesion | brim if tiny footprint | skirt | brim on corners |

**The K2 Combo has a passive enclosure (no active chamber heater).** That's fine for PLA — just
keep part cooling at 100% and **vent the enclosure door/top on long PLA prints** so trapped heat
doesn't soften the filament in the throat and clog (heat creep). The passive enclosure also means
large ABS/ASA prints warp more easily here than on the actively heated K2 Plus/Pro.

## Step 3 — Speed vs quality

The K2 is fast (CoreXY, up to 600 mm/s) but visible quality lives in the **outer wall** and
**top surface** speeds, not the headline number. Recommend:

- Slow the **outer wall** (60–100 mm/s) for figurines; the rest can stay fast.
- Keep **acceleration** moderate on detailed prints to avoid ringing/ghosting; the machine's
  input shaping helps but isn't magic.
- For first prints of a new model, drop overall speed ~20% and watch the AI camera feed.

## Step 4 — Supports

Defer to the **k2-supports** skill for the full strategy. In the slice plan, state: support type
(tree vs normal), top Z-gap, support density, and where supports will touch visible surfaces.

## Step 5 — Multi-color (CFS) workflow

For CFS jobs in Creality Print 7.1.1.4472:

1. **Use a 3MF**, not an STL, so per-object/per-color assignments survive. If given a single
   STL that needs multiple colors, split it into per-color bodies first (see stl-prep) or use
   the slicer's per-object color painting.
2. **Assign filament channels** to each color/object. Map each color to a CFS slot and list the
   mapping explicitly for the user (e.g. "Slot 1 = body PLA white, Slot 2 = accents PLA red").
3. **Control purge/flush volumes.** Color changes waste filament purging the nozzle. Lighter→
   darker transitions need more purge than darker→lighter. Recommend enabling a **flush/prime
   tower** and keeping the model's color regions contiguous to minimize changes.
4. **Minimize changes per layer.** Fewer color swaps per layer = less waste and time. Suggest
   grouping same-color geometry and using **height-based** color changes when a model is colored
   in horizontal bands.
5. **Estimate the cost.** Note added time and filament from purging so the user isn't surprised.
6. **Filament settings in a generated 3MF do not survive.** Verified from the G-code
   Creality Print keeps after each slice (on macOS:
   `/private/var/folders/…/T/crealityprint_model/<day>/<time>#…/Metadata/.<n>.0.gcode`).
   On load, every **filament-level** key is replaced by the CFS slot's system preset. That
   covers nozzle and bed temperature, part fan min/max, side (auxiliary) fan, `filament_max_volumetric_speed` and `close_fan_*`, and it held even when
   `different_settings_to_system` listed the key. Every slice read 220 °C, fan 100/100, side
   fan 80, bed 50 °C and 14 mm³/s for Generic PLA, and a slot holding Hyper PLA got the
   Hyper PLA preset. **Process** keys (speeds, walls, brim, layer heights, infill) and
   height-range modifiers do survive. So:
   - put only process settings in generated 3MFs;
   - tell the user which filament values to set by hand in the slicer;
   - or **write the preset yourself** (verified against a real slice): a JSON in
     `~/Library/Application Support/Creality/Creality Print/7.0/user/<id>/filament/` named
     `<stock name> - Copy(<tag>).json`, with `inherits` = the stock name, `base_id` (e.g. `GFSA04`),
     `from: User`, `name`/`filament_settings_id` = the new name, only the changed keys as
     one-element lists, plus a matching `.info` (copy an existing one). Creality Print reads it
     only at launch, so the user must Cmd-Q and reopen, then pick it on every filament;
   - after they slice, read that G-code header to confirm, e.g.
     `grep -E "^; (nozzle_temperature|hot_plate_temp|fan_max_speed|additional_cooling_fan_speed) =" <file>`.

   A fit test (hole gauge, clip) is only valid under the filament values it actually printed
   with, so check those too.
7. **Prime tower position.** `prime_tower_position_type` accepts only Creality's nine presets:
   Left / Middle / Right × Upper / Center / Below. Writing `Custom` makes the slicer show a
   "was replaced with Middle Upper" dialog on load. `wipe_tower_x` / `wipe_tower_y` still set
   where the tower prints, so the dialog is cosmetic (verified from a slice: the tower
   printed at the 3MF's x/y). Write `Middle Upper` plus explicit x/y in new 3MFs. Arrange may move
   the tower to the preset spot.
8. **Skirt, brim and machine keys** (measured against a real slice).
   - **Skirt:** a 3MF template copied from an older project can carry `skirt_loops 1` /
     `skirt_distance 2`. In a K2 slice that skirt runs about 7 mm outside layer 1 (brim plus gap).
     Parts packed 6.5 mm from the edge then put the skirt off the plate, and Creality refuses
     the slice. Every stock K2 process preset uses `skirt_loops 0`, so write `"skirt_loops": "0"`.
   - **`z_hop`** is a machine key: the K2 preset's 0.4 replaces the 3MF's value.
   - **Brim:** an `outer_only` brim follows notches in the first layer, such as a pocket open at
     an edge, and leaves a lip inside them. Use no brim on those parts.
   - **Fully unsupported walls:** with `detect_overhang_wall` on, walls that are 100% over air
     print at bridge speed (25), even with `enable_overhang_speed` 0.

## Step 6 — Pre-slice checklist (state these to the user)

- Model fits 255³ mm and is centered or arranged with clearance.
- Mesh is watertight/manifold (run stl-prep inspection if unsure).
- Orientation minimizes supports and puts the best face up/out.
- Thin features ≥ 0.8 mm (2 walls at 0.4 mm); flag anything thinner.
- Adhesion aid chosen (brim for tall/small-footprint).
- Supports planned.
- For CFS: color→slot mapping and flush tower decided.

## Output format

When asked to "slice" or produce a slice plan, return:

1. **Profile chosen** and one-line why.
2. **Settings table** (the actual numbers above, adjusted for this model).
3. **Supports** summary.
4. **Adhesion** choice.
5. **For CFS:** color→slot map + flush note.
6. **Rough print-time / filament estimate** if derivable.
7. **Risks / watch-outs** in one or two lines.

Then point the user to import the prepared file into Creality Print 7.1.1.4472 and dial in these
values (the studio's 🖨 button opens the displayed model, or the files a project's
`slice.json` names, in the configured slicer), or generate G-code via CLI if that path is
configured.

## Version note

UI paths and option names here track **Creality Print v7.1.1.4472**. If the user is on a
different version, say settings exist but locations may differ.
