from pathlib import Path

from secondbrain.note import Note, slugify
from secondbrain.vault import Vault


def test_roundtrip_keeps_body_and_metadata():
    note = Note(id="20261124120000", title="Spaced: repetition", tags=["a", "b c"],
                created="2026-11-24 12:00", body="\n# Hi\n\ntext\n", extra={"source": "book"})
    parsed = Note.parse(note.render())
    assert (parsed.id, parsed.title, parsed.tags, parsed.created) == (
        "20261124120000", "Spaced: repetition", ["a", "b c"], "2026-11-24 12:00")
    assert parsed.body == note.body
    assert parsed.extra == {"source": "book"}


def test_links_ignore_code_and_handle_alias_and_heading():
    body = "see [[Alpha]] and [[Beta|b]] and [[Gamma#part]] and [[Alpha]]\n`[[nope]]`\n```\n[[nope2]]\n```\n"
    assert Note.parse(body).links == ["Alpha", "Beta", "Gamma"]


def test_plain_markdown_without_frontmatter():
    note = Note.parse("# Some Idea\n\nbody", Path("idea.md"))
    assert note.id is None and note.title == "Some Idea"


def test_tags_as_string():
    assert Note.parse("---\ntags: x, y z\n---\n").tags == ["x", "y", "z"]


def test_slugify():
    assert slugify("Héllo, World! (2)") == "hello-world-2"
    assert slugify("???") == "note"


def test_vault_resolution_and_backlinks(machine):
    cfg = machine("a")
    vault = Vault(cfg)
    a = vault.create("Alpha Note", body="links to [[beta-note]]\n")
    b = vault.create("Beta Note", body="links to [[alpha note]] and [[missing]]\n")
    c = vault.create("Gamma", body=f"by id [[{a.id}]]\n")
    assert vault.resolve_link("ALPHA NOTE").id == a.id
    assert vault.resolve_link(a.id).id == a.id
    assert vault.resolve_link("beta-note").id == b.id
    assert vault.resolve_link("missing") is None
    assert {n.id for n in vault.backlinks(vault.resolve_link(a.id))} == {b.id, c.id}
    assert [n.id for n in vault.find("note")] == [a.id, b.id]


def test_ensure_ids_adopts_hand_made_files(machine):
    cfg = machine("a")
    cfg.notes_dir.mkdir(parents=True)
    (cfg.notes_dir / "loose.md").write_text("# Loose idea\n\nhello\n")
    vault = Vault(cfg)
    [fixed] = vault.ensure_ids()
    assert not (cfg.notes_dir / "loose.md").exists()
    reloaded = Note.load(fixed.path)
    assert reloaded.id == fixed.id and reloaded.title == "Loose idea"
    assert reloaded.body == "# Loose idea\n\nhello\n"
