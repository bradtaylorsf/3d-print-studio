# Examples

The studio copies each folder here into your projects folder the first time it starts
against an **empty** one, so a fresh install opens on a picture library with two finished
builds you can look at, paint, send to the slicer, or take apart. After that first copy the
studio never touches them again (a `.seeded` marker in the projects folder remembers): the
copies are yours to change, rename or archive, and this directory is only the template.
This README stays here.

| Folder | What it is | Rebuild |
|---|---|---|
| `library/refs/` | The two source pictures. Kid mode shows them as the picture library, each one linked to the build made from it. | — |
| `create_a_starfish_token/` | A chunky happy-star token, 73.6 × 70.8 × 6.2 mm, in three paintable colour parts (white backing, black outline and face, yellow fill). Flat stacked layers, so no supports. `final/` also holds the 28 mm token coin traced from the same picture. | `design.py` |
| `toybox/` | A friendly dragon, 54 × 65 × 82 mm, in four colour bodies (body, belly inlay, horns and spikes, eyes). Support-free by construction: nothing flares past 45°, and the tail lands on the bed as a third foot. `previews/dragon_views.png` shows it from four sides. | `design.py` |

## How a picture finds its build

Each build folder carries an empty `.creation` marker and a `.creation.json`:

```json
{"image": "gen_a_friendly_dragon.png", "kind": "toy"}
```

`image` is a file in `library/refs/` and `kind` is `toy` (Make me 3D) or `coin` (the traced
token coin). That is how the library shows a picture as already built and opens its model.
Asking for the same picture and kind again reuses that folder, which is what a redo is. A
folder with a non-empty `.creation` marker, or none at all, is hand-built and the studio never
rebuilds it.

## Where they came from

Original work of this project, made with the studio itself. The pictures were generated
locally with ComfyUI and Z-Image Turbo from the studio's own sticker and turnaround prompts
(the generator's embedded metadata is stripped). The models are hand-written parametric
`design.py` scripts, the kind of thing a Make me 3D build writes. No third-party models, no
people, no trademarks. Same MIT license as the rest of the repo.

## Rebuilding

Once they are in your projects folder, run a script with the studio's Python from the repo root:

```bash
.venv/bin/python projects/toybox/design.py
.venv/bin/python projects/create_a_starfish_token/design.py
```

Each one rewrites `parts/` and also writes a merged `model.stl`. That file isn't shipped, to
keep the clone small. The viewer shows `parts/` first anyway.

## Size

About 5.4 MB on disk. The two library pictures are byte-identical copies of the builds'
`refs/` pictures, so git stores each one once. If you add an example, keep it original and
small with no people in it, and run `scripts/check_privacy.py` before you open a pull request.
