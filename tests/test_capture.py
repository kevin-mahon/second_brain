import io

import pytest

from secondbrain.cli import main
from secondbrain.enrich import enrich, find_names, link_mentions, make_title, strip_filler
from secondbrain.note import Note
from secondbrain.vault import Vault


@pytest.fixture
def vault(machine):
    v = Vault(machine("c"))
    v.create("Spaced repetition", tags=["learning"], body="Review at growing intervals. [[Forgetting curve]]\n")
    v.create("Forgetting curve", tags=["learning", "memory"], body="Memory decays exponentially without review.\n")
    v.create("Ownership", tags=["rust"], body="Each value in Rust has one owner; borrowing lends it.\n")
    v.create("Borrowing", tags=["rust"], body="References borrow values from their owner in Rust.\n")
    return v


def test_titles_drop_dictation_filler():
    assert make_title("Okay so note to self. Buy a new keyboard. It's broken.") == "Buy a new keyboard"
    assert make_title("Quick thought: tabs beat spaces") == "Tabs beat spaces"
    assert make_title("x" * 100).endswith("…") and len(make_title("x" * 100)) <= 61
    assert strip_filler("um, so the build broke") == "The build broke"


def test_links_existing_titles_once_longest_first(vault):
    text, linked = link_mentions(
        "Spaced repetition fights the forgetting curve; spaced repetition again.", vault.notes()
    )
    assert text == "[[Spaced repetition]] fights the [[forgetting curve]]; spaced repetition again."
    assert [n.title for n in linked] == ["Spaced repetition", "Forgetting curve"]


def test_does_not_link_inside_existing_links(vault):
    text, _ = link_mentions("see [[Spaced repetition]]", vault.notes())
    assert text == "see [[Spaced repetition]]"


def test_names():
    assert find_names("Met Sarah Chen and The Rust Book team on Monday Morning", set()) == ["Sarah Chen", "Rust Book"]
    assert find_names("[[Sarah Chen]] again", set()) == []
    assert find_names("Sarah Chen said hi. Then Ada Lovelace", set()) == ["Sarah Chen", "Ada Lovelace"]
    assert find_names("Talked to Bob Smith", {"bob smith"}) == []


def test_enrich_suggests_tags_and_related(vault):
    result = enrich(vault, "how long until memory decays if I skip review", exclude_tags={"inbox"})
    assert "learning" in result.tags
    assert {n.title for n in result.related} & {"Forgetting curve", "Spaced repetition"}
    assert enrich(vault, "buy milk").tags == []


def test_capture_from_stdin_saves_enriched_note(vault, monkeypatch, capsys):
    cfg = vault.cfg
    from secondbrain.sync import init_vault

    init_vault(cfg, help_notes=False)
    Vault(cfg).create("Ownership", tags=["rust"], body="Rust ownership and borrowing rules.\n")
    monkeypatch.setenv("SB_HOME", str(cfg.home))
    monkeypatch.setenv("SB_KEY_FILE", str(cfg.key_file))
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO("Okay. Ownership in Rust is confusing ✨".encode())))

    assert main(["capture", "--source", "phone"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Saved “Ownership in Rust is confusing ✨”") and "#inbox" in out

    [note] = [n for n in Vault(cfg).notes() if n.extra.get("source") == "phone"]
    assert "[[Ownership]]" in note.body and "inbox" in note.tags and "rust" in note.tags
    assert isinstance(Note.parse(note.path.read_text()).extra["source"], str)


def test_capture_rejects_empty(vault, monkeypatch):
    monkeypatch.setenv("SB_HOME", str(vault.cfg.home))
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"  \n")))
    assert main(["capture", "--dry-run"]) == 1
