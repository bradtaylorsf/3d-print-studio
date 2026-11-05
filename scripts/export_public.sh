#!/usr/bin/env bash
# export_public.sh: build the public 3D Print Studio repo from this working tree.
#
#   scripts/export_public.sh <dest> [--commit] [--force]
#
# Copies an explicit ALLOWLIST. It is never "everything minus a denylist", because a new
# private file has to be opted IN before it can ship. Installs scripts/public.gitignore as
# the public .gitignore, then runs scripts/check_privacy.py on the result with
# .private-terms.txt. Only a clean tree gets `git init -b main && git add -A`. That is a
# fresh history: none of the private repo's commits come along. Nothing is ever pushed.
#
#   --force    empty a non-empty <dest> first. Only an earlier export qualifies: it may
#              not contain this repo or your home, must already hold scripts/export_public.sh
#              or studio/server.py, and may not be a git repo with a remote or history
#   --commit   also commit "Initial public release". Refused while an essential file is
#              missing, or while the commit email or name holds one of the private terms. A commit
#              email and name are public forever, so use your GitHub noreply address:
#                GIT_AUTHOR_NAME='<public name>' GIT_COMMITTER_NAME='<public name>' \
#                GIT_AUTHOR_EMAIL=<id>+<login>@users.noreply.github.com \
#                GIT_COMMITTER_EMAIL=<same> scripts/export_public.sh <dest> --commit
#
# Env: PRIVATE_TERMS=<file> uses a different terms list (default: .private-terms.txt).
#
# Bash 3.2 compatible (macOS /bin/bash): no associative arrays, no mapfile, no empty
# "${arr[@]}" under set -u.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
PUBLIC_REPO="bradtaylorsf/3d-print-studio"

# What ships. Top-level files one by one; whole trees minus junk/private names (skip_rel).
TOP_FILES="README.md SETUP.md AGENTS.md CLAUDE.md LICENSE install.sh start.sh Studio.command
requirements.txt studio.config.example.json .claude/launch.json"
TREES="scripts studio skills .claude/skills printers examples"
# --commit refuses without these: a release with no LICENSE or no installer isn't one.
ESSENTIAL="README.md SETUP.md AGENTS.md CLAUDE.md LICENSE install.sh start.sh requirements.txt
studio.config.example.json studio/server.py studio/config.py"

say()  { printf '==> %s\n' "$*"; }
warn() { printf 'warning: %s\n' "$*" >&2; }
die()  { printf 'error: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,/^set -euo/p' "$0" | sed -e '/^set -euo/d' -e 's/^# \{0,1\}//'; exit "${1:-0}"; }

# ---------------------------------------------------------------- arguments --
DEST="" COMMIT=0 FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --commit) COMMIT=1 ;;
    --force) FORCE=1 ;;
    -h|--help) usage 0 ;;
    -*) warn "unknown option $1"; usage 2 ;;
    *) [ -z "$DEST" ] || die "one destination only (got '$DEST' and '$1')"; DEST="$1" ;;
  esac
  shift
done
[ -n "$DEST" ] || usage 2

TERMS="${PRIVATE_TERMS:-$REPO/.private-terms.txt}"
[ -f "$TERMS" ] || die "no private terms file at $TERMS. The scan would be structural-only, so the export won't run without it (PRIVATE_TERMS=<file> to point elsewhere)."
[ -f "$REPO/scripts/public.gitignore" ] || die "scripts/public.gitignore is missing"
command -v git >/dev/null 2>&1 || die "git is not installed"
if [ -x "$REPO/.venv/bin/python" ]; then PY="$REPO/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then PY="$(command -v python3)"
else die "python3 is needed for scripts/check_privacy.py"; fi
# An all-comments terms file is as structural-only as a missing one.
"$PY" -I -B -c 'import sys; sys.path.insert(0, sys.argv[1]); import check_privacy as c
sys.exit(0 if c.load_terms(sys.argv[2]) else 1)' "$REPO/scripts" "$TERMS" \
  || die "$TERMS holds no terms (only comments or blank lines), so the scan would be structural-only."

# ------------------------------------------------------------- destination --
# Resolve before creating anything: a destination inside the repo must be refused
# without leaving an empty folder behind in it. Folders are compared by identity
# (samefile), never by spelling. macOS volumes are case-insensitive, so
# /users/me/documents IS /Users/me/Documents: a string-prefix check once let
# `--force` empty the folder holding this repo when the path was typed in lower case,
# and the same typo on your home folder would have emptied that.
# (A -c script, not a heredoc: bash 3.2 misparses quotes in a heredoc inside $(...).)
DEST="$("$PY" -I -c '
import os, sys
dest, repo = os.path.realpath(sys.argv[1]), os.path.realpath(sys.argv[2])
def same(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False
def chain(p):                       # p, then each parent up to /
    while True:
        yield p
        up = os.path.dirname(p)
        if up == p:
            return
        p = up
probe = next(p for p in chain(dest) if os.path.exists(p))   # deepest part that exists
if any(same(p, repo) for p in chain(probe)):
    sys.exit("error: destination %s is inside this repo" % dest)
if any(same(dest, p) for p in chain(repo)):
    sys.exit("error: destination %s contains this repo; --force would delete it" % dest)
if same(dest, os.path.expanduser("~")) or same(dest, "/"):
    sys.exit("error: refusing to use %s as the destination" % dest)
print(dest)
' "$DEST" "$REPO")" || exit 1
mkdir -p "$DEST"
if [ -n "$(ls -A "$DEST")" ]; then
  [ "$FORCE" -eq 1 ] || die "$DEST is not empty (pass --force to empty it first)"
  # --force only ever empties an earlier export. A slip like `~/Desktop --force`, or
  # the published clone with its history and remote, is never wiped by a flag.
  [ -f "$DEST/scripts/export_public.sh" ] || [ -f "$DEST/studio/server.py" ] \
    || die "$DEST is not empty and doesn't look like an earlier export (no scripts/export_public.sh or studio/server.py). Empty it yourself, or pick a new folder."
  if [ -e "$DEST/.git" ]; then
    commits="$(git -C "$DEST" rev-list --count --all 2>/dev/null || echo 0)"
    if [ -n "$(git -C "$DEST" remote 2>/dev/null)" ] || [ "${commits:-0}" -gt 1 ]; then
      die "$DEST is a git repo with a remote or more than one commit, not a fresh export. Export to a new folder, or delete this one yourself."
    fi
  fi
  say "emptying $DEST (--force)"
  find "$DEST" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
fi

# ------------------------------------------------------------------- copy --
# Paths that never ship, even inside an allowlisted tree. check_privacy.py rejects all
# of these too. Filtering here means a stray file is held back, not exported and then failed.
junk_rel() {     # skipped silently
  case "$1" in
    */__pycache__/*|__pycache__/*|*.pyc|*.pyo|.DS_Store|*/.DS_Store|*~|*.swp) return 0 ;;
    .venv*|*/.venv*|*/node_modules/*) return 0 ;;
  esac
  return 1
}
private_rel() {  # skipped and listed, so you can see what was held back
  case "$1" in
    printers/*/log.md) return 0 ;;
    CLAUDE.local.md|*/CLAUDE.local.md|*.local.md) return 0 ;;
    studio.config.json|*/studio.config.json|*studio.config.json.tmp) return 0 ;;
    .private-terms.txt|*/.private-terms.txt|*.make3d.log) return 0 ;;
    .env|*/.env|.env.*|*/.env.*)
      case "$1" in *.env.example|*.env.sample|*.env.template) return 1 ;; esac
      return 0 ;;
    *.pem|*.key|*/settings.local.json) return 0 ;;
  esac
  return 1
}

COPIED=0 HELD=""
copy_rel() {   # copy_rel <path relative to the repo>; symlinks are recreated, not followed
  local rel="$1" src="$REPO/$1" dst="$DEST/$1"
  if junk_rel "$rel"; then return 0; fi
  if private_rel "$rel"; then HELD="$HELD $rel"; return 0; fi
  mkdir -p "$(dirname "$dst")"
  if [ -L "$src" ]; then
    ln -s "$(readlink "$src")" "$dst"
  else
    cp -p "$src" "$dst"
  fi
  COPIED=$((COPIED + 1))
}

say "copying the allowlist from $REPO"
MISSING=""
for f in $TOP_FILES; do
  if [ -e "$REPO/$f" ] || [ -L "$REPO/$f" ]; then copy_rel "$f"; else MISSING="$MISSING $f"; fi
done
for t in $TREES; do
  if [ ! -d "$REPO/$t" ]; then MISSING="$MISSING $t/"; continue; fi
  while IFS= read -r -d '' p; do
    copy_rel "${p#"$REPO"/}"
  done < <(find "$REPO/$t" \( -name __pycache__ -o -name '.venv*' -o -name node_modules -o -name .git \) -prune \
             -o \( -type f -o -type l \) -print0)
done

# The data folder ships as a README only. Its own .gitignore rule keeps creations out.
if [ -f "$REPO/projects/README.md" ]; then
  copy_rel projects/README.md
else
  mkdir -p "$DEST/projects"
  cat > "$DEST/projects/README.md" <<'EOF'
# Your creations live here

The studio keeps everything you make in this folder: one folder per build, plus
`library/` for the pictures. It is gitignored apart from this README, so your projects
never end up in a commit. On first start the studio copies the seed projects from
`examples/` in here. Set `projects_dir` in `studio.config.json` to keep them somewhere else.
EOF
fi
cp "$REPO/scripts/public.gitignore" "$DEST/.gitignore"
say "copied $COPIED files (+ .gitignore, projects/README.md)"
if [ -n "$HELD" ]; then
  say "held back (private or junk, never exported):"
  for h in $HELD; do printf '      %s\n' "$h"; done
fi

# Belt and braces: nothing above copies these, but make sure none slipped in.
find "$DEST" \( -name __pycache__ -o -name .DS_Store -o -name '*.pyc' \) -prune -exec rm -rf {} +

# Every symlink has to be relative and resolve inside the tree. .claude/skills/<name> ->
# ../../skills/<name> is the case that matters: a skill renamed or removed in skills/
# leaves its link dangling.
say "checking symlinks"
"$PY" -I - "$DEST" <<'PYEOF' || die "fix the symlinks above in $REPO and re-run with --force"
import os, sys
root = os.path.realpath(sys.argv[1])
bad, n = [], 0
for d, dirs, files in os.walk(root):
    if ".git" in dirs:
        dirs.remove(".git")
    for name in dirs + files:
        p = os.path.join(d, name)
        if not os.path.islink(p):
            continue
        n += 1
        rel, target = os.path.relpath(p, root), os.readlink(p)
        real = os.path.realpath(p)
        if os.path.isabs(target):
            bad.append(f"{rel} -> {target} (absolute)")
        elif not (real == root or real.startswith(root + os.sep)):
            bad.append(f"{rel} -> {target} (outside the tree)")
        elif not os.path.exists(p):
            bad.append(f"{rel} -> {target} (dangling)")
for b in bad:
    print("  bad symlink: " + b)
print(f"    {n} symlink(s), {len(bad)} bad")
sys.exit(1 if bad else 0)
PYEOF

# ------------------------------------------------------------------ privacy --
say "privacy check (self-test first, so a broken checker can't pass anything)"
"$PY" -I "$REPO/scripts/check_privacy.py" --self-test >/dev/null \
  || die "check_privacy.py --self-test failed; run it directly to see why"
if ! "$PY" -I "$REPO/scripts/check_privacy.py" "$DEST" --terms "$TERMS" --no-git; then
  printf '\n' >&2
  die "privacy findings above. Nothing was initialised: $DEST is a plain folder, left there for inspection. Fix the files in $REPO and re-run with --force."
fi

# ---------------------------------------------------------------------- git --
say "git init (fresh history, branch main)"
git -C "$DEST" init -q -b main 2>/dev/null \
  || { git -C "$DEST" init -q && git -C "$DEST" symbolic-ref HEAD refs/heads/main; }
git -C "$DEST" add -A
STAGED="$(git -C "$DEST" diff --cached --name-only | wc -l | tr -d ' ')"
IGNORED="$(git -C "$DEST" status --porcelain --ignored | sed -n 's/^!! //p')"
say "staged $STAGED files"
if [ -n "$IGNORED" ]; then
  warn "copied but ignored by the public .gitignore, so NOT in the repo:"
  printf '%s\n' "$IGNORED" | sed 's/^/      /' >&2
fi

if [ -n "$MISSING" ]; then
  warn "allowlisted but missing from the working tree:$MISSING"
fi
ESS_MISSING=""
for f in $ESSENTIAL; do [ -e "$DEST/$f" ] || ESS_MISSING="$ESS_MISSING $f"; done

COMMITTED=0
if [ "$COMMIT" -eq 1 ]; then
  [ -z "$ESS_MISSING" ] || die "not committing: essential files missing:$ESS_MISSING"
  ident="$(git -C "$DEST" var GIT_AUTHOR_IDENT 2>/dev/null || true)"
  cident="$(git -C "$DEST" var GIT_COMMITTER_IDENT 2>/dev/null || true)"
  [ -n "$ident" ] || die "no git identity: set user.name and user.email (git config --global ...)"
  email="$(printf '%s' "$ident" | sed -n 's/.*<\(.*\)>.*/\1/p')"
  cemail="$(printf '%s' "$cident" | sed -n 's/.*<\(.*\)>.*/\1/p')"
  aname="$(printf '%s' "$ident" | sed -n 's/^\(.*\) <.*/\1/p')"
  cname="$(printf '%s' "$cident" | sed -n 's/^\(.*\) <.*/\1/p')"
  # LICENSE's copyright holder is the one name the release publishes on purpose (LICENSE
  # is exempt from the term scan), so a commit under exactly that name is allowed.
  holder="$(sed -n 's/^Copyright (c) [0-9, -]* //p' "$DEST/LICENSE" 2>/dev/null | head -1)"
  holder_hint=""
  [ -z "$holder" ] || holder_hint=" (the LICENSE name, $holder, is allowed)"
  for e in "$email" "$cemail" "$aname" "$cname"; do
    [ -n "$e" ] || continue
    [ -n "$holder" ] && [ "$e" = "$holder" ] && continue
    # The checker's own whole-word match, not an exact line: <username>@icloud.com
    # contains a private term just as surely as the listed address does.
    # 10 = private, 0 = clean, anything else (a crash is 1) = couldn't check.
    rc=0
    "$PY" -I -B -c 'import sys; sys.path.insert(0, sys.argv[1]); import check_privacy as c
rx = c.term_regex(c.load_terms(sys.argv[2])); sys.exit(10 if rx and rx.search(sys.argv[3]) else 0)' \
      "$REPO/scripts" "$TERMS" "$e" || rc=$?
    [ "$rc" -eq 0 ] || [ "$rc" -eq 10 ] || die "not committing: could not check the commit email against $TERMS"
    if [ "$rc" -eq 10 ]; then
      case "$e" in
        *@*) die "not committing: the commit email $e contains one of your private terms, and a commit email is public forever. Re-run with your GitHub noreply address:
  GIT_AUTHOR_EMAIL=<id>+<login>@users.noreply.github.com GIT_COMMITTER_EMAIL=<same> $0 $DEST --commit --force
(the address is under GitHub > Settings > Emails)" ;;
        *) die "not committing: the commit name '$e' contains one of your private terms, and commit metadata is public forever. Re-run with the name you want public$holder_hint:
  GIT_AUTHOR_NAME='<name>' GIT_COMMITTER_NAME='<name>' GIT_AUTHOR_EMAIL=<noreply> GIT_COMMITTER_EMAIL=<noreply> $0 $DEST --commit --force" ;;
      esac
    fi
  done
  git -C "$DEST" -c commit.gpgsign=false commit -q -m "Initial public release"
  COMMITTED=1
  say "committed as: $ident"
  case "$email" in
    *@users.noreply.github.com) ;;
    # The names go into the tip too: --reset-author falls back to user.name, which may
    # be the private name a one-off GIT_AUTHOR_NAME was set to replace.
    *) warn "the commit email $email will be public. A GitHub noreply address (<id>+<login>@users.noreply.github.com) keeps it private; to switch: GIT_AUTHOR_NAME=$(printf %q "$aname") GIT_COMMITTER_NAME=$(printf %q "$cname") GIT_AUTHOR_EMAIL=... GIT_COMMITTER_EMAIL=... git -C $DEST commit --amend --reset-author --no-edit" ;;
  esac
fi

# ------------------------------------------------------------------ summary --
say "size: tree $(du -sh "$DEST" | cut -f1) on disk, git objects $(du -sh "$DEST/.git" | cut -f1)"
say "largest files:"
find "$DEST" -path "$DEST/.git" -prune -o -type f -exec du -k {} + 2>/dev/null \
  | sort -rn | head -8 | while read -r kb path; do printf '      %6s KB  %s\n' "$kb" "${path#"$DEST"/}"; done

echo
if [ -n "$ESS_MISSING" ]; then
  warn "essential files missing (add them before publishing):$ESS_MISSING"
fi
echo "Public tree ready at $DEST. Nothing has been pushed."
echo "Next steps (your call):"
echo "  git -C \"$DEST\" status --short | head          # review what ships"
if [ "$COMMITTED" -eq 0 ]; then
  # Re-run with --commit rather than a bare `git commit`: only --commit checks the commit
  # name and email against the private terms, and a bare commit takes user.name.
  echo "  GIT_AUTHOR_NAME='<public name>' GIT_COMMITTER_NAME='<public name>' \\"
  echo "  GIT_AUTHOR_EMAIL=<noreply> GIT_COMMITTER_EMAIL=<noreply> \\"
  echo "    $0 \"$DEST\" --commit --force"
fi
echo "  gh repo create $PUBLIC_REPO --public --source \"$DEST\" --push"
