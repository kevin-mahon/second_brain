import subprocess

import pytest

from secondbrain.config import SBError
from secondbrain.crypto import create_key
from secondbrain.help_notes import HELP_NOTES
from secondbrain.sync import Syncer, init_vault
from secondbrain.vault import Vault


def git(cfg, *args) -> str:
    return subprocess.run(["git", *args], cwd=cfg.home, check=True, capture_output=True, text=True).stdout


def titles(cfg) -> set[str]:
    return {n.title for n in Vault(cfg).notes()}


def note_named(cfg, title):
    [note] = [n for n in Vault(cfg).notes() if n.title == title]
    return note


def sync(cfg):
    return Syncer(cfg).sync()


@pytest.fixture
def two_machines(machine, remote):
    a, b = machine("a"), machine("b")
    _, created = init_vault(a, remote=remote)
    assert created
    init_vault(b, remote=remote)
    return a, b


def test_init_seeds_encrypted_help_notes(machine, remote):
    a = machine("a")
    report, _ = init_vault(a, remote=remote)
    assert report.pushed
    assert titles(a) == {t for t, _, _ in HELP_NOTES}
    tracked = git(a, "ls-files").split()
    assert ".gitignore" in tracked
    assert all(p == ".gitignore" or (p.startswith("vault/") and p.endswith(".enc")) for p in tracked)
    assert len(tracked) == len(HELP_NOTES) + 1
    # Neither content nor titles leak into the repo.
    assert not any("welcome" in p for p in tracked)
    for path in tracked:
        if path.endswith(".enc"):
            data = (a.home / path).read_text()
            assert "Welcome" not in data


def test_second_machine_clones_and_decrypts(two_machines):
    a, b = two_machines
    assert titles(b) == titles(a)
    assert sorted(p.name for p in b.notes_dir.iterdir()) == sorted(p.name for p in a.notes_dir.iterdir())


def test_unchanged_notes_are_not_reencrypted(two_machines):
    a, _ = two_machines
    head = git(a, "rev-parse", "HEAD")
    sync(a)
    sync(a)
    assert git(a, "rev-parse", "HEAD") == head


def test_edit_create_delete_rename_propagate(two_machines):
    a, b = two_machines
    welcome = note_named(a, "Welcome to sb")
    welcome.path.write_text(welcome.path.read_text() + "\nedited on a\n")
    new = Vault(a).create("Fresh idea", tags=["x"], body="hello [[Welcome to sb]]\n")
    gone = note_named(a, "Finding notes")
    gone.path.unlink()
    moved = note_named(a, "Linking notes")
    moved.path.rename(moved.path.with_name(f"{moved.id}-renamed.md"))

    sync(a)
    changed = git(a, "show", "--name-only", "--format=", "HEAD").split()
    assert len(changed) == 4  # only the touched notes were re-encrypted

    report = sync(b)
    assert report.received == 4
    assert "edited on a" in note_named(b, "Welcome to sb").path.read_text()
    assert note_named(b, "Fresh idea").id == new.id
    assert "Finding notes" not in titles(b)
    assert (b.notes_dir / f"{moved.id}-renamed.md").exists()
    assert not list(b.notes_dir.glob(f"{moved.id}-linking*"))


def test_conflict_keeps_both_versions(two_machines):
    a, b = two_machines
    for cfg, text in ((a, "from a"), (b, "from b")):
        note = note_named(cfg, "Welcome to sb")
        note.path.write_text(note.path.read_text() + f"\n{text}\n")
    sync(a)

    report = sync(b)
    assert len(report.conflicts) == 1 and report.pushed
    assert "from a" in note_named(b, "Welcome to sb").path.read_text()
    copy = note_named(b, report.conflicts[0])
    assert "from b" in copy.path.read_text()
    assert copy.id != note_named(b, "Welcome to sb").id

    sync(a)
    assert titles(a) == titles(b)


def test_delete_vs_edit_keeps_the_edit(two_machines):
    a, b = two_machines
    note_named(a, "Finding notes").path.unlink()
    sync(a)
    edited = note_named(b, "Finding notes")
    edited.path.write_text(edited.path.read_text() + "\nkeep me\n")
    sync(b)
    sync(a)
    assert "keep me" in note_named(a, "Finding notes").path.read_text()


def test_offline_commits_locally_then_pushes(machine, tmp_path):
    a = machine("a")
    init_vault(a)
    git(a, "remote", "add", "origin", str(tmp_path / "does-not-exist.git"))
    Vault(a).create("Offline thought")
    report = sync(a)
    assert report.network == "offline" and report.unpushed and report.sent == 1
    assert "1 note(s)" in git(a, "log", "-1", "--format=%s")


def test_offline_flag_skips_network(two_machines, machine):
    a, _ = two_machines
    a_off = machine("a", offline=True)
    Vault(a_off).create("Later")
    report = sync(a_off)
    assert report.network == "skipped" and report.unpushed
    assert sync(a).pushed


def test_clone_without_key_explains(machine, remote, key_file):
    init_vault(machine("a"), remote=remote)
    key_file.unlink()
    with pytest.raises(SBError, match="no key"):
        init_vault(machine("b"), remote=remote)


def test_wrong_key_is_reported(machine, remote, key_file):
    init_vault(machine("a"), remote=remote)
    key_file.unlink()
    create_key(machine("b"))
    with pytest.raises(SBError, match="doesn't match"):
        init_vault(machine("b"), remote=remote)


def test_a_few_notes_under_another_key_are_skipped_not_fatal(machine, remote, tmp_path):
    from dataclasses import replace

    a = machine("a")
    init_vault(a, remote=remote, help_notes=False)
    Vault(a).create("Readable", body="fine\n")
    sync(a)

    # A machine joins, then ends up with a different key and adds a note.
    init_vault(machine("b"), remote=remote, help_notes=False)
    stray = replace(machine("b"), key_file=tmp_path / "other-key")
    create_key(stray)
    Vault(stray).create("Written with another key", body="?\n")
    sync(stray)

    report = sync(a)  # must not raise
    assert len(report.unreadable) == 1
    assert titles(a) == {"Readable"}
    Vault(a).create("Still works", body="\n")
    assert sync(a).pushed
