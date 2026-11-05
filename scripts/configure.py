#!/usr/bin/env python3
"""configure.py — read and change studio.config.json from the shell. Stdlib only.

    scripts/configure.py init                       copy studio.config.example.json if there's no config
    scripts/configure.py set KEY VALUE [KEY VALUE…]  merge values into the file
    scripts/configure.py get KEY                    print the effective value (defaults < file < env)
    scripts/configure.py unset KEY [KEY…]           drop keys from the file (back to the default)
    scripts/configure.py show [--file]              print the effective config (or just the file)
    scripts/configure.py path                       print the config file's path

KEY is dotted (`kid.grown_up`, `printer.bed_mm`). VALUE is parsed as JSON when it
parses (`4`, `true`, `[260,260,260]`, `"quoted"`), else taken as a plain string —
so `set kid.grown_up Mom` just works. `--string` keeps every value a string
(install.sh uses it for names: a grown-up called "null" must not become null).

Unknown keys and values of the wrong type are refused, because a typo like
`kid.grownup` would otherwise be written, ignored, and look like a bug in the
studio. `--force` writes them anyway.

Runs with any python3 — no venv needed (install.sh calls it before deps exist).
"""
import difflib
import json
import math
import os
import shutil
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "studio"))
import config  # noqa: E402  (studio/config.py — the shared settings contract)

EXAMPLE = os.path.join(REPO, "studio.config.example.json")
BACKEND_VALUES = ("auto", "claude", "comfyui", "comfy", "nano")


def die(msg, code=1):
    print(f"configure.py: {msg}", file=sys.stderr)
    sys.exit(code)


def known_keys(d=None, prefix=""):
    """Every dotted key in DEFAULTS, leaves and branches."""
    d = config.DEFAULTS if d is None else d
    out = []
    for k, v in d.items():
        key = prefix + k
        out.append(key)
        if isinstance(v, dict):
            out.extend(known_keys(v, key + "."))
    return out


def parse_value(raw, as_string):
    if as_string:
        return raw
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _kind(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number" if math.isfinite(v) else "NaN/Infinity"   # as config._kind
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "list"
    if isinstance(v, dict):
        return "object"
    return "null"


def check(key, value):
    """None if fine, else why not."""
    keys = known_keys()
    if key not in keys:
        close = difflib.get_close_matches(key, keys, n=3)
        hint = f" — did you mean {' or '.join(close)}?" if close else ""
        return f"unknown key '{key}'{hint}"
    default = config.get_path(config.DEFAULTS, key)
    if _kind(default) != _kind(value):
        kind = _kind(default)
        return (f"'{key}' wants {'an' if kind[0] in 'aeiou' else 'a'} {kind} "
                f"(default {json.dumps(default)}), got {json.dumps(value)}")
    # the same rule config.load() applies: a negative (or NaN) number falls back to its default
    if _kind(value) == "number" and value < 0:
        return f"'{key}' wants a number of 0 or more (default {json.dumps(default)}), got {json.dumps(value)}"
    if key == "image_backend" and str(value).lower() not in BACKEND_VALUES:
        return f"image_backend must be one of {', '.join(BACKEND_VALUES)}"
    if key == "printer.bed_mm" and (len(value) != 3 or not all(
            _kind(v) == "number" and v > 0 for v in value)):
        return "printer.bed_mm wants three positive numbers, e.g. [260,260,260]"
    if key == "options" and not 1 <= int(value) <= 8:
        return "options must be 1..8"
    if isinstance(value, dict):      # `set printer '{"bed_mm": 260}'` gets the same checks
        for k, v in value.items():
            why = check(f"{key}.{k}", v)
            if why:
                return why
    return None


def cmd_init(_args):
    path = config.CONFIG_PATH
    if os.path.isfile(path):
        print(f"{rel(path)} already exists — kept as is")
        return 0
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.isfile(EXAMPLE):
        shutil.copyfile(EXAMPLE, path)
        print(f"created {rel(path)} from {rel(EXAMPLE)}")
    else:
        config.save({}, path)
        print(f"created {rel(path)} (empty — defaults apply)")
    return 0


def cmd_set(args):
    # flags only before the first KEY: a value that happens to be "-s" (a
    # grown-up's name typed into install.sh) must stay a value
    as_string = force = False
    rest = list(args)
    while rest and rest[0] in ("--string", "-s", "--force", "-f", "--"):
        flag = rest.pop(0)
        if flag == "--":
            break
        if flag in ("--string", "-s"):
            as_string = True
        else:
            force = True
    if not rest or len(rest) % 2:
        die("usage: configure.py set [--string] [--force] KEY VALUE [KEY VALUE ...]")
    updates, problems = {}, []
    for key, raw in zip(rest[::2], rest[1::2]):
        value = parse_value(raw, as_string)
        if key == "image_backend" and isinstance(value, str):
            value = value.strip().lower()
            value = "comfyui" if value == "comfy" else value
        why = None if force else check(key, value)
        if why:
            problems.append(why)
        else:
            config.set_path(updates, key, value)
    if problems:
        die("; ".join(problems) + "  (nothing written; --force overrides)")
    try:
        config.save(updates)
    except ValueError as e:          # the existing file is broken JSON
        die(f"{e} — fix it by hand, or move it aside and run `configure.py init`")
    except OSError as e:             # e.g. $STUDIO_CONFIG in a folder that doesn't exist
        die(f"can't write {config.CONFIG_PATH}: {e.strerror or e}")
    for key, raw in zip(rest[::2], rest[1::2]):
        print(f"{key} = {json.dumps(config.get_path(updates, key))}")
    return 0


def cmd_unset(args):
    if not args:
        die("usage: configure.py unset KEY [KEY ...]")
    try:
        data = config.read_file()
    except ValueError as e:
        die(str(e))
    changed = False
    for key in args:
        parts = key.split(".")
        cur = data
        for p in parts[:-1]:
            cur = cur.get(p) if isinstance(cur, dict) else None
        if isinstance(cur, dict) and parts[-1] in cur:
            cur.pop(parts[-1])
            changed = True
            print(f"{key} removed (default {json.dumps(config.get_path(config.DEFAULTS, key))})")
        else:
            print(f"{key} was not set")
    if not changed:
        return 0
    path = config.CONFIG_PATH
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    except OSError as e:
        die(f"can't write {path}: {e.strerror or e}")
    return 0


def cmd_get(args):
    if len(args) != 1:
        die("usage: configure.py get KEY")
    cfg = config.load()
    if cfg.get("_error"):
        print(f"configure.py: warning: {cfg['_error']} (showing defaults)", file=sys.stderr)
    for w in cfg.get("_warnings") or []:
        print(f"configure.py: warning: {w}", file=sys.stderr)
    missing = object()
    value = config.get_path(cfg, args[0], missing)
    if value is missing:
        die(f"no such key '{args[0]}'")
    print(value if isinstance(value, str) else json.dumps(value))
    return 0


def cmd_show(args):
    if "--file" in args:
        try:
            print(json.dumps(config.read_file(), indent=2))
        except ValueError as e:
            die(str(e))
        return 0
    cfg = config.load()
    print(f"# {rel(cfg['_path'])}" + ("" if cfg["_exists"] else " (missing — defaults shown)")
          + (f"  ERROR: {cfg['_error']}" if cfg.get("_error") else ""), file=sys.stderr)
    for w in cfg.get("_warnings") or []:
        print(f"# warning: {w}", file=sys.stderr)
    print(json.dumps({k: v for k, v in cfg.items() if not k.startswith("_")}, indent=2))
    return 0


def cmd_path(_args):
    print(config.CONFIG_PATH)
    return 0


def rel(p):
    try:
        r = os.path.relpath(p)
    except ValueError:
        return p
    return p if r.startswith("..") else r


COMMANDS = {"init": cmd_init, "set": cmd_set, "unset": cmd_unset, "get": cmd_get,
            "show": cmd_show, "path": cmd_path}


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    cmd = COMMANDS.get(argv[0])
    if not cmd:
        die(f"unknown command '{argv[0]}' (try: {', '.join(COMMANDS)})")
    return cmd(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
