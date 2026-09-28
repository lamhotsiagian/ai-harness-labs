"""Execution sandbox: path jail, command allowlist, scrubbed env, egress policy.

This is the process-level rung of the trust ladder (Chapter 11). It is enough to
make the labs safe on a laptop. For hostile code, run the same workspace inside
the container command produced by `Sandbox.container_command()` (gVisor or
Firecracker for multi-tenant production).
"""
from __future__ import annotations

import fnmatch
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from .tools import ToolError

SHELL_METACHARS = set(";|&`$><\n")


@dataclass
class EgressPolicy:
    allowlist: list[str] = field(default_factory=list)   # host globs; ["*"] = open egress
    log: list[dict] = field(default_factory=list)

    def check(self, url: str, method: str = "GET", body: str = "") -> bool:
        host = urlparse(url).hostname or ""
        allowed = any(fnmatch.fnmatch(host, pat) for pat in self.allowlist)
        self.log.append({"url": url, "host": host, "method": method, "allowed": allowed,
                         "bytes": len(body), "body_preview": body[:200]})
        return allowed


@dataclass
class Sandbox:
    root: Path
    allowed_commands: tuple[str, ...] = ("python", "python3", "ls", "cat", "grep", "wc", "head", "git")
    egress: EgressPolicy = field(default_factory=EgressPolicy)
    protected_globs: tuple[str, ...] = (".env", ".git/*")
    violations: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve()

    # ------------------------------------------------------------ filesystem
    def resolve(self, rel: str, for_write: bool = False) -> Path:
        """Map a model-supplied path into the jail or raise a ToolError."""
        candidate = (self.root / rel).resolve()   # resolve() follows symlinks
        try:
            relative = candidate.relative_to(self.root)
        except ValueError:
            self.violations.append({"kind": "path_escape", "path": rel})
            raise ToolError(f"path '{rel}' escapes the workspace",
                            "use paths relative to the repository root")
        if for_write and any(fnmatch.fnmatch(str(relative), g) for g in self.protected_globs):
            self.violations.append({"kind": "protected_write", "path": rel})
            raise ToolError(f"'{rel}' is protected", "secrets and VCS metadata are read-only")
        return candidate

    # ------------------------------------------------------------ processes
    def scrubbed_env(self) -> dict[str, str]:
        """Only what a test run needs: no cloud credentials, no host HOME."""
        return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.root),
                "PYTHONDONTWRITEBYTECODE": "1", "LANG": "C.UTF-8"}

    def run(self, command: str, timeout: int = 30) -> tuple[int, str]:
        if any(ch in SHELL_METACHARS for ch in command):
            self.violations.append({"kind": "shell_metachar", "command": command})
            raise ToolError("shell operators are not allowed",
                            "run one command at a time without pipes, redirects, or ';'")
        argv = shlex.split(command)
        if not argv or argv[0] not in self.allowed_commands:
            self.violations.append({"kind": "command_denied", "command": command})
            raise ToolError(f"command '{argv[0] if argv else ''}' is not on the allowlist",
                            f"allowed commands: {', '.join(self.allowed_commands)}")
        if argv[0] in ("python", "python3"):
            argv[0] = sys.executable
        for arg in argv[1:]:
            if arg.startswith("/") or ".." in arg:
                self.resolve(arg)             # raises on escape
        try:
            proc = subprocess.run(argv, cwd=self.root, env=self.scrubbed_env(), capture_output=True,
                                  text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ToolError(f"command timed out after {timeout}s", "narrow the command scope")
        return proc.returncode, (proc.stdout + proc.stderr)

    def container_command(self, image: str = "python:3.12-slim", runtime: str | None = None) -> list[str]:
        """Equivalent hardened container invocation for Lab 11 (Docker or gVisor)."""
        cmd = ["docker", "run", "--rm", "--network", "none", "--read-only",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--pids-limit", "256", "--memory", "1g", "--cpus", "1",
               "--tmpfs", "/tmp:rw,size=64m", "-v", f"{self.root}:/workspace:rw",
               "-w", "/workspace"]
        if runtime:
            cmd += ["--runtime", runtime]      # e.g. runsc for gVisor
        return cmd + [image]
