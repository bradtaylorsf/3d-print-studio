#!/usr/bin/env python3
"""build_guard.py — what a headless "Make me 3D" build may do. Stdlib only.

"Make me 3D" starts Claude Code with nobody watching, on a picture a child
chose (or a grown-up imported from a URL). It used to run with
`--permission-mode bypassPermissions`: every tool, anywhere, as your user.
This file is what replaced that. It has two halves:

1. `claude_args()` — the launch flags studio/server.py appends to `claude -p`:
   permission mode `dontAsk` (anything not allowed is refused, never asked),
   two allow rules (the repo's own Python, edits inside the build's project
   folder), web tools denied, and this file registered as a PreToolUse hook.

2. The hook itself (`python build_guard.py --repo … --project …`, JSON on
   stdin, one call per tool use). It refuses anything outside this policy,
   whatever the user's own Claude settings allow:

     read    this repo and the projects folder — not .git, not key files
     write   the build's own project folder, nothing else — and no agent
             instructions or settings there (CLAUDE.md, .claude/, .mcp.json)
     Bash    one command per call: the repo's Python and its arguments.
             No other program, no pipes, &&, redirects, cd or $(...)
     other   no web, no subagents, no MCP, no tool this file doesn't know

   Two layers on purpose: the flags hold if hooks are switched off, the hook
   holds if a user-level allow rule (say `Bash(*)`) would loosen the flags.

What this does NOT cover: the Python the build runs is ordinary Python. A
design.py can open any file your user can and reach the network. Stopping
that takes an operating-system sandbox, which is `claude.build_sandbox`
(see `sandbox_settings`): Claude Code's own sandbox, confining the Python
process to the project folder with no network.

Fails closed: a hook input it can't read, or a bug in here, refuses the call.
"""
import argparse
import json
import os
import re
import shlex
import sys

# file_path-style input key per tool (None: the tool takes an optional `path`)
READ_TOOLS = {"Read": "file_path", "NotebookRead": "notebook_path", "Glob": None, "Grep": None}
WRITE_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path",
               "NotebookEdit": "notebook_path"}
# no file or network reach of their own: skills, the to-do list, and minding
# the build's own background commands
PLAIN_TOOLS = {"Skill", "ToolSearch", "TodoWrite", "TaskCreate", "TaskUpdate", "TaskGet",
               "TaskList", "TaskOutput", "TaskStop", "BashOutput", "KillShell", "KillBash"}
DENIED_TOOLS = ("WebFetch", "WebSearch")      # also deny rules in the launch settings

# files a later agent session would load as instructions or settings: a build
# has no reason to leave one behind in a project folder
AGENT_FILES = {"claude.md", "claude.local.md", "agents.md", ".mcp.json"}
GLOB_CHARS = set("*?[{")
STDERR_TO_STDOUT = re.compile(r"\s+2>&1\s*$")


class Refused(Exception):
    """The reason goes back to the build agent, so it says what to do instead."""


def real(path, cwd=None):
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(cwd or os.getcwd(), path)
    return os.path.realpath(path)             # follows symlinks: a link out of the folder is out


def inside(path, root):
    try:
        return os.path.commonpath([path, root]) == root
    except ValueError:                        # different drives (Windows)
        return False


class Policy:
    def __init__(self, repo, project, projects_root, python):
        self.repo = os.path.realpath(repo)
        self.project = os.path.realpath(project)
        self.projects_root = os.path.realpath(projects_root)
        self.python = python                  # compared as written: the path the prompt gives

    # ------------------------------------------------------------ files --
    def check_read(self, path, cwd, extra_roots=()):
        target = real(path, cwd)
        roots = (self.repo, self.projects_root) + tuple(extra_roots)
        if not any(inside(target, r) for r in roots):
            raise Refused(f"{path} is outside the studio. A Make me 3D build reads only "
                          f"{self.repo} and its projects folder.")
        name = os.path.basename(target).lower()
        if (".git" in target.split(os.sep) or name.startswith(".env")
                or name.endswith((".pem", ".key")) or "gemini_key" in name):
            raise Refused(f"{path} is not for a build to read (git internals and key files are off limits).")

    def check_write(self, path, cwd):
        if not path:
            raise Refused("no file path given")
        target = real(path, cwd)
        if not inside(target, self.project):
            raise Refused(f"{path} is outside this build's project folder. A Make me 3D build "
                          f"writes only inside {self.project}.")
        parts = os.path.relpath(target, self.project).lower().split(os.sep)
        if parts[-1] in AGENT_FILES or any(p in (".claude", ".git") for p in parts):
            raise Refused(f"{path} is an agent instruction or settings file; a build doesn't write those.")

    # ------------------------------------------------------------- Bash --
    def check_bash(self, command):
        """One simple command: the repo's Python and its arguments. Returns argv."""
        how = (f"A Make me 3D build runs one program, one command per Bash call: {shlex.quote(self.python)} "
               "followed by its arguments (a trailing 2>&1 is fine). No cd, pipes, &&, redirects, "
               "$variables or other programs — read files with the Read tool, and list a folder "
               f"or check a mesh with {shlex.quote(self.python)} -c '...'.")
        if not isinstance(command, str) or not command.strip():
            raise Refused(how)
        command = STDERR_TO_STDOUT.sub("", command)
        bad = shell_syntax(command)
        if bad:
            raise Refused(f"{bad} is not allowed. {how}")
        try:
            argv = shlex.split(command)
        except ValueError as error:
            raise Refused(f"could not parse the command ({error}). {how}")
        if not argv or argv[0] != self.python:
            raise Refused(how)
        return argv

    # ------------------------------------------------------------ verdict --
    def decide(self, event):
        """None = no objection (Claude Code's own permission rules decide);
        "allow" = this call is approved here; raises Refused otherwise."""
        tool = event.get("tool_name") or ""
        inp = event.get("tool_input")
        inp = inp if isinstance(inp, dict) else {}
        cwd = event.get("cwd") or self.repo
        if tool in READ_TOOLS:
            key = READ_TOOLS[tool]
            path = inp.get(key) if key else (inp.get("path") or cwd)
            if tool == "Glob":
                path = glob_base(inp.get("pattern") or "", path)
            if not path:
                raise Refused("no file path given")
            self.check_read(path, cwd, session_scratch(event))
            return None
        if tool in WRITE_TOOLS:
            self.check_write(inp.get(WRITE_TOOLS[tool]), cwd)
            return None
        if tool == "Bash":
            if inp.get("dangerouslyDisableSandbox"):
                raise Refused("a Make me 3D build never runs a command outside the sandbox")
            self.check_bash(inp.get("command"))
            # A path with a space has to be quoted in the command, and the
            # `Bash(<python> *)` allow rule can't match a quoted program, so
            # the checked command is approved here. Otherwise say nothing and
            # let that allow rule be the second check.
            return "allow" if shlex.quote(self.python) != self.python else None
        if tool in PLAIN_TOOLS:
            return None
        raise Refused(f"the {tool} tool is not available to a Make me 3D build. Work with Read, "
                      "Write, Edit and the repo's Python.")


def shell_syntax(command):
    """Name the first piece of shell syntax that could start a second command,
    expand a value or redirect output — or None. Quotes are honoured the way
    bash does: nothing is special inside '...', and inside "..." only $ and `."""
    quote = None
    i = 0
    while i < len(command):
        ch = command[i]
        if quote == "'":
            if ch == "'":
                quote = None
        elif ch == "\\":
            i += 1                            # the next character is literal
        elif quote == '"':
            if ch == '"':
                quote = None
            elif ch in "$`":
                return f"{ch} (shell expansion)"
        elif ch in "'\"":
            quote = ch
        elif ch in "\n\r":
            return "a second line"
        elif ch in ";&|<>()$`":
            return f"{ch}"
        i += 1
    return None


def glob_base(pattern, path):
    """Where a Glob really looks: an absolute pattern ignores `path`."""
    pattern = os.path.expanduser(pattern)
    if ".." in pattern.replace("\\", "/").split("/"):
        raise Refused("a glob pattern with .. is not allowed")
    if not os.path.isabs(pattern):
        return path
    keep = []
    for part in pattern.split(os.sep):
        if GLOB_CHARS & set(part):
            break
        keep.append(part)
    return os.sep.join(keep) or os.sep


def session_scratch(event):
    """Claude Code saves an oversized tool result (a long Python traceback)
    next to the session transcript and tells the agent to Read it there."""
    transcript, session = event.get("transcript_path"), event.get("session_id")
    if not (isinstance(transcript, str) and isinstance(session, str) and session
            and os.sep not in session and ".." not in session):
        return ()
    return (os.path.join(os.path.realpath(os.path.dirname(os.path.expanduser(transcript))), session),)


# ---------------------------------------------------------------- launch --
def permission_path(path):
    """An absolute path in Claude Code's permission-rule syntax (`//abs`)."""
    return "/" + os.path.abspath(path).replace(os.sep, "/")


def sandbox_settings(repo, project, projects_root):
    """Claude Code's OS sandbox (Seatbelt on macOS, bubblewrap on Linux) for
    every command the build runs — the part no hook can do. The Python may
    write inside the project folder (and the sandbox's own temp folder) and
    has no network at all.

    The sandbox lets a command write under the session's working directory,
    which is the whole repo, and a deny beats an allow — so every sibling of
    the path down to the project folder is denied by name."""
    repo, project, root = (os.path.realpath(p) for p in (repo, project, projects_root))
    deny = []

    def deny_siblings(folder, keep):
        for name in sorted(os.listdir(folder)):
            path = os.path.join(folder, name)
            if path != keep:
                deny.append(path)

    if inside(root, repo):
        walk = repo
        for part in os.path.relpath(project, repo).split(os.sep):
            deny_siblings(walk, os.path.join(walk, part))
            walk = os.path.join(walk, part)
    else:
        deny.append(repo)
        deny_siblings(root, project)
    return {
        "enabled": True,
        "failIfUnavailable": True,            # never quietly run unsandboxed instead
        "allowUnsandboxedCommands": False,
        "autoAllowBashIfSandboxed": False,    # the allow rule and the hook still decide
        "network": {"allowedDomains": [], "strictAllowlist": True},
        "filesystem": {"allowWrite": [project], "denyWrite": deny},
    }


def claude_args(repo, project, projects_root, python, sandbox=False):
    """What `claude -p <prompt>` gets instead of --permission-mode bypassPermissions."""
    hook = [sys.executable or python, os.path.abspath(__file__), "--repo", repo, "--project", project,
            "--projects-root", projects_root, "--python", python]
    settings = {
        "permissions": {
            "allow": [f"Bash({python} *)", f"Edit({permission_path(project)}/**)"],
            "deny": list(DENIED_TOOLS),
        },
        "hooks": {"PreToolUse": [{"matcher": "*", "hooks": [
            {"type": "command", "command": shlex.join(hook), "timeout": 15}]}]},
    }
    if sandbox:
        settings["sandbox"] = sandbox_settings(repo, project, projects_root)
    # dontAsk: whatever no rule allows is refused, and nothing ever prompts
    return ["--permission-mode", "dontAsk", "--settings", json.dumps(settings)]


# ------------------------------------------------------------------ hook --
def answer(decision, reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": reason}}))


def main(argv=None):
    ap = argparse.ArgumentParser(description="PreToolUse hook for Make me 3D builds")
    for flag in ("--repo", "--project", "--projects-root", "--python"):
        ap.add_argument(flag, required=True)
    try:
        args = ap.parse_args(argv)
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            raise ValueError("hook input is not an object")
        verdict = Policy(args.repo, args.project, args.projects_root, args.python).decide(event)
    except Refused as refusal:
        answer("deny", str(refusal))
        return 0
    except (SystemExit, Exception) as error:  # noqa: BLE001 — fail closed, whatever it was
        answer("deny", f"the build guard could not check this call ({error})")
        return 0
    if verdict == "allow":
        answer("allow", "the repo's Python, checked by studio/build_guard.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
