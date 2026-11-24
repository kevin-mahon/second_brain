"""Thin wrapper around the git CLI."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .config import SBError

BRANCH = "main"
REMOTE = "origin"


class Git:
    def __init__(self, root: Path, timeout: float):
        self.root = root
        self.timeout = timeout

    def run(self, *args: str, check: bool = True, network: bool = False) -> subprocess.CompletedProcess:
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        if network and "GIT_SSH_COMMAND" not in env:
            # Never hang waiting for a password: sb runs this on every call.
            env["GIT_SSH_COMMAND"] = f"ssh -o BatchMode=yes -o ConnectTimeout={max(1, int(self.timeout))}"
        cmd = ["git", "-c", "commit.gpgsign=false", "-c", "core.quotepath=off", *args]
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.root,
                env=env,
                capture_output=True,
                timeout=self.timeout + 2 if network else None,
            )
        except FileNotFoundError:
            raise SBError("git is not installed") from None
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(cmd, 124, b"", b"timed out")
        if check and proc.returncode != 0:
            raise SBError(f"git {' '.join(args)} failed: {proc.stderr.decode(errors='replace').strip()}")
        return proc

    def out(self, *args: str, check: bool = True) -> str:
        return self.run(*args, check=check).stdout.decode("utf-8", errors="replace").strip()

    # -- queries ------------------------------------------------------------

    def is_repo(self) -> bool:
        return (self.root / ".git").exists()

    def has_remote(self) -> bool:
        return REMOTE in self.out("remote", check=False).split()

    def ref_exists(self, ref: str) -> bool:
        return self.run("rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0

    def has_staged_changes(self) -> bool:
        return self.run("diff", "--cached", "--quiet", check=False).returncode == 1

    def ahead_of_remote(self) -> bool:
        if not self.ref_exists("HEAD"):
            return False
        remote_ref = f"{REMOTE}/{BRANCH}"
        if not self.ref_exists(remote_ref):
            return True
        return self.out("rev-list", "--count", f"{remote_ref}..HEAD") != "0"

    def show_stage(self, stage: int, path: str) -> bytes | None:
        proc = self.run("show", f":{stage}:{path}", check=False)
        return proc.stdout if proc.returncode == 0 else None

    def conflicted_paths(self) -> list[str]:
        return [p for p in self.out("diff", "--name-only", "--diff-filter=U").splitlines() if p]

    # -- network ------------------------------------------------------------

    def fetch(self) -> bool:
        return self.run("fetch", "--quiet", REMOTE, check=False, network=True).returncode == 0

    def push(self) -> bool:
        proc = self.run("push", "--quiet", "-u", REMOTE, f"HEAD:{BRANCH}", check=False, network=True)
        return proc.returncode == 0
