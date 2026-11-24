"""Encrypted git sync.

Layout of the vault home (default ~/.sb):

    notes/          plaintext markdown, what you edit. Git-ignored.
    vault/<id>.enc  one encrypted file per note. Committed and pushed.
    .sb-state.json  hashes from the last sync, so only changed notes are
                    re-encrypted (Fernet output differs on every run, so
                    re-encrypting everything would rewrite every file).

A sync runs in this order:

    1. encrypt notes that changed locally, delete removed ones, commit
    2. fetch + merge the remote (bounded by a timeout; offline is fine)
    3. decrypt anything that changed remotely into notes/
    4. push if we have commits the remote doesn't

Git can't merge two encrypted versions of one note, so on a conflict the
remote version wins and the local version is kept as a separate
"(conflict from <host>)" note for you to merge by hand. Nothing is lost.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config, SBError
from .crypto import Cipher, create_key, key_exists
from .gitrepo import BRANCH, REMOTE, Git
from .note import Note, new_id
from .vault import Vault

GITIGNORE = """\
# Plaintext notes and local sync state never leave this machine.
notes/
.sb-state.json
"""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _host() -> str:
    return socket.gethostname().split(".")[0] or "unknown-host"


@dataclass
class SyncReport:
    sent: int = 0
    received: int = 0
    conflicts: list[str] = field(default_factory=list)
    adopted: list[str] = field(default_factory=list)
    network: str = "skipped"  # ok | offline | no-remote | skipped
    pushed: bool = False
    unpushed: bool = False


class Syncer:
    def __init__(self, cfg: Config, vault: Vault | None = None):
        self.cfg = cfg
        self.git = Git(cfg.home, cfg.timeout)
        if not self.git.is_repo():
            raise SBError(f"no vault at {cfg.home}. Run `sb init` first.")
        self.cipher = Cipher(cfg)
        self.vault = vault or Vault(cfg)
        self.state: dict[str, dict] = self._load_state()

    # -- state --------------------------------------------------------------

    def _load_state(self) -> dict[str, dict]:
        try:
            return json.loads(self.cfg.state_file.read_text())["notes"]
        except FileNotFoundError:
            return {}
        except (ValueError, KeyError):
            print("sb: sync state was unreadable; rebuilding it", file=sys.stderr)
            return {}

    def _save_state(self) -> None:
        tmp = self.cfg.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "notes": self.state}, indent=1, sort_keys=True))
        os.replace(tmp, self.cfg.state_file)

    def _enc_path(self, note_id: str) -> Path:
        return self.cfg.vault_dir / f"{note_id}.enc"

    # -- 1. local -> vault ----------------------------------------------------

    def commit_local(self, report: SyncReport) -> None:
        self.cfg.notes_dir.mkdir(parents=True, exist_ok=True)
        self.cfg.vault_dir.mkdir(parents=True, exist_ok=True)
        report.adopted += [n.path.name for n in self.vault.ensure_ids()]

        changed = 0
        seen: set[str] = set()
        for note in self.vault.notes():
            assert note.id and note.path
            if note.id in seen:
                print(f"sb: {note.path.name} reuses ID {note.id}; skipping it. Give it a new id.", file=sys.stderr)
                continue
            seen.add(note.id)

            raw = note.path.read_bytes()
            plain = _sha(raw)
            entry = self.state.get(note.id)
            enc = self._enc_path(note.id)
            if entry and entry["plain"] == plain and entry["name"] == note.path.name and enc.exists():
                continue
            blob = self.cipher.encrypt(note.path.name, raw.decode("utf-8"))
            enc.write_bytes(blob)
            self.state[note.id] = {"plain": plain, "cipher": _sha(blob), "name": note.path.name}
            changed += 1

        for note_id in list(self.state):
            if note_id not in seen:
                self._enc_path(note_id).unlink(missing_ok=True)
                del self.state[note_id]
                changed += 1

        self._save_state()
        self.git.run("add", "-A", "--", "vault", ".gitignore")
        if self.git.has_staged_changes():
            self.git.run("commit", "-q", "-m", f"sb: {changed} note(s) from {_host()}")
        report.sent += changed

    # -- 2. remote -> vault ---------------------------------------------------

    def pull(self, report: SyncReport) -> None:
        if not self.git.has_remote():
            report.network = "no-remote"
            return
        if not self.git.fetch():
            report.network = "offline"
            return
        report.network = "ok"
        remote_ref = f"{REMOTE}/{BRANCH}"
        if not self.git.ref_exists(remote_ref):
            return
        proc = self.git.run(
            "merge", "-q", "--no-edit", "--allow-unrelated-histories",
            "-m", "sb: merge remote changes", remote_ref,
            check=False,
        )
        if proc.returncode == 0:
            return
        conflicts = self.git.conflicted_paths()
        if not conflicts:
            raise SBError(f"git merge failed: {proc.stderr.decode(errors='replace').strip()}")
        self._resolve_conflicts(conflicts, report)

    def _resolve_conflicts(self, paths: list[str], report: SyncReport) -> None:
        for path in paths:
            ours = self.git.show_stage(2, path)
            theirs = self.git.show_stage(3, path)
            if path.startswith("vault/") and ours is not None and theirs is not None:
                _, text = self.cipher.decrypt(ours)
                report.conflicts.append(self._write_conflict_copy(text))
            # Remote wins when both sides have the file; a modification beats a deletion.
            keep = theirs if theirs is not None else ours
            if keep is None:
                self.git.run("rm", "-q", "--", path)
            else:
                (self.cfg.home / path).write_bytes(keep)
                self.git.run("add", "--", path)
        self.git.run("commit", "-q", "--no-edit")

    def _write_conflict_copy(self, text: str) -> str:
        note = Note.parse(text)
        taken = self.vault.ids() | set(self.state) | {p.stem for p in self.cfg.vault_dir.glob("*.enc")}
        note.id = new_id(taken)
        note.title = f"{note.title} (conflict from {_host()})"
        note.path = self.cfg.notes_dir / note.filename
        note.path.write_text(note.render(), encoding="utf-8")
        self.vault.refresh()
        return note.title

    # -- 3. vault -> local ----------------------------------------------------

    def apply_remote(self, report: SyncReport) -> None:
        encs = {p.stem: p for p in self.cfg.vault_dir.glob("*.enc")}
        changed = 0
        for note_id, enc in sorted(encs.items()):
            blob = enc.read_bytes()
            cipher = _sha(blob)
            entry = self.state.get(note_id)
            if entry and entry["cipher"] == cipher:
                continue
            name, text = self.cipher.decrypt(blob)
            name = Path(name).name
            if not name.endswith(".md") or name.startswith("."):
                name = f"{note_id}.md"
            data = text.encode("utf-8")
            if entry and entry["name"] != name:
                (self.cfg.notes_dir / entry["name"]).unlink(missing_ok=True)
            (self.cfg.notes_dir / name).write_bytes(data)
            self.state[note_id] = {"plain": _sha(data), "cipher": cipher, "name": name}
            changed += 1

        for note_id in list(self.state):
            if note_id not in encs:
                (self.cfg.notes_dir / self.state[note_id]["name"]).unlink(missing_ok=True)
                del self.state[note_id]
                changed += 1

        if changed:
            self._save_state()
            self.vault.refresh()
        report.received += changed

    # -- all together -----------------------------------------------------------

    def sync(self, network: bool = True) -> SyncReport:
        report = SyncReport()
        self.commit_local(report)
        if network and not self.cfg.offline:
            self.pull(report)
        self.apply_remote(report)
        if report.conflicts:
            self.commit_local(report)  # pick up the conflict copies
        if self.git.ahead_of_remote():
            if report.network == "ok" and self.git.push():
                report.pushed = True
            else:
                report.unpushed = report.network != "no-remote"
        return report


def init_vault(cfg: Config, remote: str | None = None, help_notes: bool = True) -> tuple[SyncReport, bool]:
    """Create the vault (optionally cloning an existing remote). Returns (report, key_created)."""
    from .help_notes import write_help_notes

    git = Git(cfg.home, cfg.timeout)
    cfg.home.mkdir(parents=True, exist_ok=True)
    key_created = False

    if git.is_repo():
        if not remote:
            raise SBError(f"{cfg.home} is already a vault. Use `sb init --remote URL` to add a remote.")
        git.run("remote", "set-url" if git.has_remote() else "add", REMOTE, remote)
        if not git.fetch():
            raise SBError(f"could not reach {remote}")
        return Syncer(cfg).sync(), key_created

    git.run("init", "-q", "-b", BRANCH)
    cfg.notes_dir.mkdir(exist_ok=True)
    cfg.vault_dir.mkdir(exist_ok=True)

    remote_has_vault = False
    if remote:
        git.run("remote", "add", REMOTE, remote)
        if not git.fetch():
            raise SBError(f"could not reach {remote}. Fix that, then re-run `sb init --remote {remote}`.")
        remote_has_vault = git.ref_exists(f"{REMOTE}/{BRANCH}")

    if remote_has_vault:
        git.run("checkout", "-q", "-B", BRANCH, "--track", f"{REMOTE}/{BRANCH}")
        if not key_exists(cfg):
            raise SBError(
                f"cloned the vault, but there is no key at {cfg.key_file}. "
                "Copy it from your other machine, then run `sb sync`."
            )
    else:
        if not key_exists(cfg):
            create_key(cfg)
            key_created = True
        (cfg.home / ".gitignore").write_text(GITIGNORE)
        git.run("add", ".gitignore")
        git.run("commit", "-q", "-m", "sb: initialise vault")
        if help_notes:
            write_help_notes(Vault(cfg))

    return Syncer(cfg).sync(), key_created
