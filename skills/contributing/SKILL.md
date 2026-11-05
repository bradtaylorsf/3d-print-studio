---
name: contributing
description: >-
  Problem-driven lifecycle for any change or pull request to this repo: problem → research →
  hypothesis → smallest experiment → build to the house style → verify → PR. Use whenever
  someone wants to add or fix something here, says "create a PR" / "open a pull request", or is
  thinking out loud about an improvement to the studio, the skills or the tools.
---

# contributing — problem-driven changes and PRs for this repo

Use this skill when someone wants to add something to this project, fix something, "create
a PR", or is thinking out loud about an improvement. It applies to humans pairing with
an agent (Claude Code, Codex, …) and to agents working solo. Do not skip stages — the order
is the point. If the user arrives solution-first ("let's add X"), walk backwards to Stage 1
first.

## Stage 1 — Problem statement (no solutions allowed yet)

Write, in the chat, three sentences max:
- **Who hurts and when**: the actual moment ("when a new user drops a 90MB STL, the page
  freezes 3s with no feedback").
- **Evidence**: a session transcript, a capture, a failed print photo, an error — something
  that happened, not something that might.
- **Cost of doing nothing**: why this matters enough to change code.

If there is no evidence yet, stop and go make some (reproduce it). A problem you can't
reproduce is a rumor. Park solution ideas that leak in — literally write "parked: ..." and
move on.

## Stage 2 — Research first

Before proposing anything:
1. **Search this repo** — the fix may exist: check `skills/*/SKILL.md`, `studio/server.py`
   endpoints, `studio/static/app.js`, meshtools subcommands. Half of "missing features"
   are undocumented existing ones — then the fix is docs, which is a smaller PR.
2. **Check open issues/PRs** (`gh issue list`, `gh pr list`) so work isn't duplicated.
3. **Reproduce the problem locally** and note exact steps — these become your verification
   steps later.
4. Record what you learned in one short paragraph. An agent should spend real tool calls
   here; a contribution whose research section is empty gets bounced.

## Stage 3 — Hypothesis

One sentence, falsifiable, with a measurable signal:

> We believe **\<specific change\>** will **\<observable outcome\>** for **\<who\>**,
> and we'll know it worked when **\<signal we can check\>**.

Example: "We believe parsing STLs in a Web Worker will keep the viewer responsive during
90MB loads, and we'll know it worked when the camera can orbit during a 90 MB reload."

If you can't fill in the signal, return to Stage 1 — you don't understand the problem yet.

## Stage 4 — Smallest experiment

Design the least work that tests the hypothesis: one endpoint, one function, one skill
section — not a framework. Explicitly list what you are NOT doing (out-of-scope creep is
named, not silently included). If the experiment could invalidate the hypothesis cheaply
(a 10-line spike, a manual test), run it before writing the real change.

## Stage 5 — Build to the house style

- **Server**: Python stdlib only. No pip deps for `studio/server.py`, ever. JSON errors,
  curl-testable endpoints, filenames whitelisted (see existing handlers for the pattern).
- **Settings**: never hard-code a printer size, a path, a model name or a port. Read them
  through `studio/config.py` (`studio.config.json` < environment); add a new key to its
  `DEFAULTS` and to `studio.config.example.json` together.
- **Client**: vanilla ES modules, no framework, no build step, no CDN at runtime.
  three.js stays vendored (`studio/vendor.sh` to upgrade).
- **Geometry**: parametric `design.py` per project, mm units, bed coordinates (Z ≥ 0),
  watertight before "print-ready". Reuse `skills/stl-prep/meshtools.py` helpers.
- **Skills**: plain markdown `skills/<name>/SKILL.md` with `name`/`description` frontmatter,
  written as instructions to an agent, with a "when to use" first line. When adding one,
  update the skills list in `AGENTS.md` and add its symlink:
  `ln -s ../../skills/<name> .claude/skills/<name>`.
- **Privacy**: no personal names, absolute home-directory paths, photos of people
  or private print logs in tracked files. Personal printer notes go in
  `printers/<slug>/log.md`, which the public repo ignores. `scripts/check_privacy.py <dir>`
  scans a tree for exactly this.
- **Naming**: lowercase_underscores, trailing dimension in mm for meshes.

## Stage 6 — Verify like a reviewer

Re-run the reproduction steps from Stage 2 and confirm the Stage 3 signal flipped. For
studio changes: exercise the endpoint with `curl` AND click through the page. For geometry:
`meshtools.py info` the output and view it in the studio. Paste the actual output into the
chat — "it works" without output doesn't count.

## Stage 7 — Ship the PR

```bash
git checkout -b <problem-slug>        # e.g. worker-stl-parse, not "improvements"
git add <files> && git commit         # subject: the change; body: the problem
gh pr create --title "..." --body-file <generated body>
```

PR body template (fill every section; delete none):

```markdown
## Problem
<who hurts, when — from Stage 1, with the evidence>

## Hypothesis
We believe <change> will <outcome>, measured by <signal>.

## What I did
<the smallest-experiment scope, incl. what was deliberately left out>

## Verification
<exact commands/clicks + pasted output showing the signal flipped>

## Risks / follow-ups
<what could break, what's parked>
```

If an agent wrote the change, say so in the PR body, and keep whatever attribution line your
agent adds to its commits.

## Quick reference: contribution ideas by lifecycle stage

| You have... | Do |
|---|---|
| A vague itch ("uploads feel clunky") | Stage 1: turn it into a reproducible moment |
| A repro + evidence | Stage 3: write the hypothesis |
| A hypothesis | Stage 4: scope the smallest experiment |
| Working code, no evidence trail | Go back: reconstruct Stages 1–3 honestly before the PR |
