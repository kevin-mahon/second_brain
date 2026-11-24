import pytest

from secondbrain import picker
from secondbrain.cli import App, note_candidates, shell_candidates
from secondbrain.config import SBError
from secondbrain.vault import Vault


@pytest.fixture
def vault(machine):
    v = Vault(machine("p"))
    v.create("Zettelkasten in a nutshell", tags=["zettelkasten"])
    v.create("Atomic notes", tags=["zettelkasten", "writing"])
    v.create("Spaced repetition", tags=["learning"])
    v.create("Repetition in music")
    return v


def titles(notes):
    return [n.title for n in notes]


def test_find_matches_titles_and_tags_best_first(vault):
    assert titles(vault.find("zett")) == ["Zettelkasten in a nutshell", "Atomic notes"]
    assert titles(vault.find("repetition")) == ["Repetition in music", "Spaced repetition"]
    assert titles(vault.find("spa rep")) == ["Spaced repetition"]  # every word must match
    assert titles(vault.find("learn")) == ["Spaced repetition"]  # via tag


def test_find_falls_back_to_fuzzy(vault):
    assert titles(vault.find("zkn")) == ["Zettelkasten in a nutshell"]
    assert vault.find("qqq") == []


def test_completion_prefers_prefixes_then_a_unique_fuzzy_match(vault):
    assert note_candidates(vault, "spa") == ["spaced-repetition"]
    assert note_candidates(vault, "nutsh") == ["zettelkasten-in-a-nutshell"]
    assert note_candidates(vault, "repetition") == ["repetition-in-music"]  # slug prefix wins
    assert note_candidates(vault, "petit") == []  # ambiguous: left to the picker
    assert len(note_candidates(vault, "")) == 4


def test_shell_candidates(vault):
    cfg = vault.cfg
    assert shell_candidates(cfg, ["sb", "ed"], 1) == ["edit"]
    assert shell_candidates(cfg, ["sb", "e", "ato"], 2) == ["atomic-notes"]
    assert shell_candidates(cfg, ["sb", "-n", "rm", "spa"], 3) == ["spaced-repetition"]
    assert shell_candidates(cfg, ["sb", "ls", "-t", "zet"], 3) == ["zettelkasten"]
    assert "--depth" in shell_candidates(cfg, ["sb", "graph", "--d"], 2)
    assert shell_candidates(cfg, ["sb", "new", "x"], 2) == []


def test_pick_non_interactive_lists_matches(vault, monkeypatch):
    monkeypatch.setattr(picker, "interactive", lambda: False)
    app = App(vault.cfg, sync=False)
    assert app.pick(["spa"]).title == "Spaced repetition"
    with pytest.raises(SBError, match="matches 2 notes"):
        app.pick(["zett"])


def test_pick_menu(vault, monkeypatch):
    monkeypatch.setattr(picker, "interactive", lambda: True)
    monkeypatch.setenv("SB_PICKER", "builtin")
    answers = iter(["2"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    app = App(vault.cfg, sync=False)
    assert app.pick(["zett"]).title == "Atomic notes"

    answers = iter(["music"])  # narrowing to one match picks it
    assert app.pick([]).title == "Repetition in music"

    answers = iter([""])
    with pytest.raises(SBError, match="nothing picked"):
        app.pick(["zett"])
