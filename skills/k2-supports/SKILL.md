---
name: k2-supports
description: >-
  Plan and configure supports for FDM prints on the Creality K2 in Creality Print 7.1.1.4472.
  Use whenever the user asks about supports, overhangs, bridging, "will this need supports",
  removing supports cleanly, tree vs normal supports, support density/Z-gap, or painting/blocking
  supports on a model. Tuned for PLA figurines and functional parts on the repo's shipped
  default printer (the K2); the method carries to any FDM printer. Trigger on: "support",
  "overhang", "tree support", "supports breaking the surface", "hard to remove".
---

# K2 Supports

Goal: get reliable supports that hold the print up but come off cleanly and don't scar visible
surfaces. Most **figurines need supports**; many **functional parts can be reoriented to avoid
them**. Always try orientation first (see stl-prep), then add supports.

Numbers below are for PLA on a Creality K2 with Creality Print 7.1.1.4472, the printer this
repo ships tuned for. On another printer or slicer the strategy is the same; take
temperatures and option names from its `printers/<slug>/profile.md` (the printer-setup
skill writes one if it's missing). A model built for a
child ("Make me 3D") should be designed to need **no supports at all** — flat base, chunky
shapes, overhangs ≤ 45°.

## Step 1 — Decide if supports are needed

- **Overhang rule:** anything steeper than **~45–55° from vertical** needs support. Walls up to
  ~50° usually print clean on PLA with good cooling.
- **Bridges:** flat spans under ~10 mm usually bridge fine without support; longer spans sag.
- **Small flat overhang ledges** (a few mm) can print as unsupported "eaves." Larger ones need
  support or a chamfer.
- **First instinct: reorient.** Rotating a part to put overhangs near-vertical or onto the bed
  often removes the need for supports entirely. Recommend this before adding material.

## Step 2 — Choose support type

| Type | Best for | Trade-offs |
|---|---|---|
| **Tree (organic)** | figurines, organic shapes, models with sparse contact points | Less material, easier removal, touches fewer surfaces; can be unstable on wide flat overhangs |
| **Normal (grid/linear)** | wide flat overhangs, functional parts, large bridges | Strong and predictable; uses more material, can scar surfaces, harder to remove |
| **Hybrid** | tall figurines with both | Tree for the body, normal under wide ledges |

Default for figurines: **tree supports**. Default under wide flat functional overhangs:
**normal**.

## Step 3 — Key settings (PLA, K2)

| Setting | Recommended | Why |
|---|---|---|
| Support type | Tree (figurines) / Normal (flat overhangs) | see above |
| Overhang threshold | 45–50° | below this, no support |
| Top Z-gap (support → model) | **0.20–0.25 mm** (≈1 layer at 0.2 mm) | the single biggest factor in easy removal |
| Support density | 8–15% | enough to hold, easy to snap off |
| Interface layers | 2 (on) | cleaner surface where support meets model |
| Interface Z-gap | tight (≈0.15–0.2 mm) | smooth contact face |
| Support pattern | zig-zag / lines | snaps off in strips |
| XY distance from model | 0.5–0.8 mm | avoids fusing to walls |
| Build-plate-only? | yes when possible | far easier than part-on-part support |

**Removal-first tuning:** if supports are tearing the surface, *increase the top Z-gap* slightly
(0.25–0.3 mm) and lower interface density. If supports are detaching mid-print or the surface
sags, *decrease the gap* and add an interface layer.

## Step 4 — Painting & blocking supports (Creality Print 7.1.1.4472)

The slicer lets you manually add (paint) or remove (block) supports per region:

- **Paint supports** on a critical overhang the auto-generator missed (e.g. an outstretched arm,
  a chin, a cape edge).
- **Block supports** ("support blocker" / paint-off) on cosmetic faces where you'd rather risk a
  small overhang than scar the surface — faces, smooth fronts, lettering.
- For figurines, **keep supports off the face and front detail** wherever the overhang is mild;
  let those areas print as steep walls instead.

State explicitly to the user **which surfaces supports will touch** so they know where cleanup
and possible marks will be.

## Step 5 — Easy-removal tips

- Tree supports + 0.2–0.25 mm top gap + 2 interface layers ≈ supports that peel/snap by hand.
- Print supports a touch hotter is unnecessary on PLA; instead rely on the Z-gap.
- For deep crevices, plan access — if pliers/flush-cutters can't reach, reorient or split the
  model (stl-prep) so the supported area is exposed.
- After removal, a quick pass with a hobby knife or fine sanding cleans nubs; mention this for
  display figurines.

## Output format

When asked about supports, return:

1. **Reorient first?** — whether rotating the model reduces/eliminates supports, and how.
2. **Type** (tree/normal/hybrid) and why.
3. **Settings** (top Z-gap, density, interface, threshold).
4. **Where supports touch the model** and any cosmetic risk.
5. **Paint/block** recommendations for specific regions.
6. **Removal note.**
