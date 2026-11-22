#!/usr/bin/env python3
"""The Make me 3D build guard must refuse what a build has no business doing,
and must not get in the way of what a build needs. Stdlib only:
python scripts/test_build_guard.py"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "studio"))
import build_guard  # noqa: E402
from build_guard import Policy, Refused  # noqa: E402


class GuardCase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="guard-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = os.path.join(self.tmp, "studio repo")          # a space, on purpose
        self.root = os.path.join(self.repo, "projects")
        self.project = os.path.join(self.root, "dragon_toy")
        self.other = os.path.join(self.root, "rocket_toy")
        for d in (self.project, self.other, os.path.join(self.repo, "studio"),
                  os.path.join(self.repo, ".git"), os.path.join(self.repo, "skills", "stl-prep")):
            os.makedirs(d)
        self.python = os.path.join(self.repo, ".venv", "bin", "python")
        self.policy = Policy(self.repo, self.project, self.root, self.python)

    def event(self, tool, **tool_input):
        return {"tool_name": tool, "tool_input": tool_input, "cwd": self.repo,
                "session_id": "abc123", "transcript_path": os.path.join(self.tmp, "claude", "abc123.jsonl")}

    def ok(self, tool, **tool_input):
        return self.policy.decide(self.event(tool, **tool_input))

    def refused(self, tool, **tool_input):
        with self.assertRaises(Refused, msg=f"{tool} {tool_input}"):
            self.policy.decide(self.event(tool, **tool_input))


class Files(GuardCase):
    def test_writes_stay_in_the_project(self):
        self.ok("Write", file_path=os.path.join(self.project, "design.py"), content="x")
        self.ok("Edit", file_path="projects/dragon_toy/parts/parts.json")      # relative to the repo
        self.ok("NotebookEdit", notebook_path=os.path.join(self.project, "n.ipynb"))
        for path in (os.path.join(self.repo, "studio", "server.py"),
                     os.path.join(self.other, "design.py"),
                     os.path.join(self.repo, "studio.config.json"),
                     os.path.join(self.repo, ".claude", "settings.json"),
                     os.path.join(self.project, "..", "rocket_toy", "model.stl"),
                     self.project + "_evil/design.py",          # a prefix is not a parent
                     "/etc/passwd", "~/.zshrc", ""):
            self.refused("Write", file_path=path, content="x")
            self.refused("Edit", file_path=path)

    def test_a_symlink_out_of_the_project_is_out(self):
        os.symlink(self.other, os.path.join(self.project, "link"))
        self.refused("Write", file_path=os.path.join(self.project, "link", "model.stl"))

    def test_reads_stay_in_the_studio(self):
        self.ok("Read", file_path=os.path.join(self.repo, "AGENTS.md"))
        self.ok("Read", file_path="skills/stl-prep/SKILL.md")
        self.ok("Read", file_path=os.path.join(self.project, "refs", "dragon.png"))
        self.ok("Grep", pattern="trimesh")                                   # no path: the repo
        self.ok("Glob", pattern="skills/*/SKILL.md")
        self.ok("Glob", pattern=os.path.join(self.repo, "skills", "**", "*.py"))
        for path in ("/etc/passwd", "~/.ssh/id_ed25519", os.path.join(self.repo, ".git", "config"),
                     os.path.join(self.repo, ".env"), os.path.join(self.repo, ".env.local"),
                     os.path.join(self.repo, "server.pem"), os.path.join(self.tmp, "elsewhere.txt")):
            self.refused("Read", file_path=path)
        self.refused("Grep", pattern="key", path="/etc")
        self.refused("Glob", pattern="/etc/**")
        self.refused("Glob", pattern="../../**/*.key")

    def test_projects_folder_outside_the_repo(self):
        root = os.path.join(self.tmp, "my toys")
        project = os.path.join(root, "dragon_toy")
        os.makedirs(project)
        policy = Policy(self.repo, project, root, self.python)
        event = self.event("Write", file_path=os.path.join(project, "design.py"))
        self.assertIsNone(policy.decide(event))
        self.assertIsNone(policy.decide(self.event("Read", file_path=os.path.join(root, "library", "refs", "a.png"))))
        with self.assertRaises(Refused):
            policy.decide(self.event("Write", file_path=os.path.join(self.repo, "projects", "x.py")))

    def test_oversized_tool_results_can_be_read_back(self):
        saved = os.path.join(self.tmp, "claude", "abc123", "tool-results", "toolu_1.txt")
        self.ok("Read", file_path=saved)
        self.refused("Read", file_path=os.path.join(self.tmp, "claude", "other-session", "x.txt"))


class Bash(GuardCase):
    def test_the_repo_python_runs(self):
        py = build_guard.shlex.quote(self.python)
        for command in (f"{py} projects/dragon_toy/design.py",
                        f"{py} design.py --size 80 2>&1",
                        f"{py} -c 'import trimesh; print(trimesh.load(\"model.stl\").is_watertight)'",
                        f"{py} -c \"\nimport os\nprint(os.listdir('projects/dragon_toy'))\n\"",
                        f"{py} -c 'print(\"a; b | c && d > e $(f) `g`\")'",    # inert inside '...'
                        f"{py} skills/stl-prep/meshtools.py info model.stl"):
            # the python path has a space, so the guard itself approves the checked command
            self.assertEqual(self.ok("Bash", command=command), "allow", command)

    def test_a_plain_path_leaves_the_decision_to_the_allow_rule(self):
        policy = Policy(self.repo, self.project, self.root, "/opt/studio/.venv/bin/python")
        event = self.event("Bash", command="/opt/studio/.venv/bin/python design.py")
        self.assertIsNone(policy.decide(event))

    def test_nothing_else_runs(self):
        py = build_guard.shlex.quote(self.python)
        for command in ("ls", "rm -rf projects", "curl https://example.com", "git push", "pip install x",
                        "python design.py", ".venv/bin/python design.py", "/usr/bin/python3 design.py",
                        f"FOO=1 {py} design.py", f"cd projects && {py} design.py",
                        f"{py} design.py && rm -rf projects/rocket_toy", f"{py} design.py; ls",
                        f"{py} design.py | tail -5", f"{py} design.py > studio/server.py",
                        f"{py} design.py >> out.txt", f"{py} design.py < /etc/passwd",
                        f"{py} design.py &", f"{py} design.py\nrm -rf projects",
                        f"{py} $(cat /etc/passwd)", f"{py} `id`", f"{py} -c \"print('$HOME')\"",
                        f"{py} -c \"`id`\"", f"({py} design.py)", f"{py} design.py 2>&1 | tee x",
                        f"{py} -c 'unterminated", "", "   "):
            self.refused("Bash", command=command)
        self.refused("Bash", command=f"{py} design.py", dangerouslyDisableSandbox=True)


class Tools(GuardCase):
    def test_only_known_tools(self):
        for tool in ("Skill", "TodoWrite", "ToolSearch", "TaskStop"):
            self.assertIsNone(self.ok(tool))
        for tool in ("WebFetch", "WebSearch", "Task", "Agent", "mcp__github__push_files", "SomethingNew", ""):
            self.refused(tool)


class Launch(GuardCase):
    def test_flags_replace_bypass(self):
        args = build_guard.claude_args(self.repo, self.project, self.root, self.python)
        self.assertNotIn("bypassPermissions", " ".join(args))
        self.assertEqual(args[:4], ["--permission-mode", "dontAsk", "--permission-prompts", "none"])
        settings = json.loads(args[args.index("--settings") + 1])
        self.assertEqual(settings["permissions"]["allow"],
                         [f"Bash({self.python} *)", f"Edit(/{self.project}/**)"])
        self.assertIn("WebFetch", settings["permissions"]["deny"])
        hook = settings["hooks"]["PreToolUse"][0]
        self.assertEqual(hook["matcher"], "*")
        self.assertEqual(build_guard.shlex.split(hook["hooks"][0]["command"])[1:],
                         [os.path.abspath(build_guard.__file__), "--repo", self.repo, "--project",
                          self.project, "--projects-root", self.root, "--python", self.python])
        self.assertNotIn("sandbox", settings)

    def test_sandbox_denies_every_sibling(self):
        open(os.path.join(self.repo, "studio.config.json"), "w").close()
        args = build_guard.claude_args(self.repo, self.project, self.root, self.python, sandbox=True)
        sandbox = json.loads(args[args.index("--settings") + 1])["sandbox"]
        self.assertTrue(sandbox["enabled"] and sandbox["failIfUnavailable"])
        self.assertFalse(sandbox["allowUnsandboxedCommands"])
        self.assertEqual(sandbox["network"]["allowedDomains"], [])
        deny = sandbox["filesystem"]["denyWrite"]
        for path in (os.path.join(self.repo, "studio"), os.path.join(self.repo, ".git"),
                     os.path.join(self.repo, "studio.config.json"), self.other):
            self.assertIn(path, deny)
        for path in (self.repo, self.root, self.project):
            self.assertNotIn(path, deny)
        self.assertEqual(sandbox["filesystem"]["allowWrite"], [self.project])


class Hook(GuardCase):
    def run_hook(self, stdin, argv=None):
        argv = argv if argv is not None else ["--repo", self.repo, "--project", self.project,
                                              "--projects-root", self.root, "--python", self.python]
        out, old = io.StringIO(), sys.stdin
        sys.stdin = io.StringIO(stdin)
        try:
            with redirect_stdout(out), redirect_stderr(io.StringIO()):
                code = build_guard.main(argv)
        finally:
            sys.stdin = old
        return code, (json.loads(out.getvalue())["hookSpecificOutput"] if out.getvalue() else None)

    def test_deny_allow_and_silence(self):
        code, said = self.run_hook(json.dumps(self.event("Bash", command="rm -rf /")))
        self.assertEqual((code, said["permissionDecision"]), (0, "deny"))
        code, said = self.run_hook(json.dumps(self.event("Read", file_path="AGENTS.md")))
        self.assertEqual((code, said), (0, None))

    def test_fails_closed(self):
        for stdin, argv in (("not json", None), ("[]", None),
                            (json.dumps(self.event("Read", file_path="AGENTS.md")), ["--repo", self.repo])):
            code, said = self.run_hook(stdin, argv)
            self.assertEqual((code, said["permissionDecision"]), (0, "deny"))


if __name__ == "__main__":
    unittest.main()
