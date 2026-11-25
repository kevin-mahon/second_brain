"""The commands the iPhone Shortcuts use: search → pick a line → read it → follow links."""

import io

import pytest

from secondbrain.cli import main, ssh_gate_argv
from secondbrain.config import SBError
from secondbrain.vault import Vault


@pytest.fixture
def env(machine, monkeypatch, capsys):
    from secondbrain.sync import init_vault

    cfg = machine("phone")
    init_vault(cfg, help_notes=False)
    v = Vault(cfg)
    v.create("Spaced repetition", tags=["learning"], body="\n# Spaced repetition\n\nReview often. See [[Forgetting curve|the curve]].\n")
    v.create("Forgetting curve", tags=["learning", "memory"], body="\n# Forgetting curve\n\nMemory decays.\n")
    v.create("Ownership in Rust", tags=["rust"], body="One owner per value.\n")
    monkeypatch.setenv("SB_HOME", str(cfg.home))
    monkeypatch.setenv("SB_KEY_FILE", str(cfg.key_file))
    monkeypatch.setenv("SB_OFFLINE", "1")

    def run(argv, stdin=""):
        monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(stdin.encode())))
        code = main(argv)
        return code, capsys.readouterr().out

    return run


def test_search_lines_from_stdin_then_read_the_picked_line(env):
    code, out = env(["search", "--lines", "-"], "Repetition.\n")  # dictation adds the period
    assert code == 0
    [line] = out.splitlines()
    assert line.startswith("Spaced repetition · #learning · 2")

    code, out = env(["show", "--md", "-"], line)
    assert code == 0
    assert out.startswith("# Spaced repetition\n\nReview often. See **the curve**.")
    assert "#learning · Created " in out and "**Links to**\n\n- → Forgetting curve\n" in out
    assert "id:" not in out  # no frontmatter


def test_link_lines_in_the_reading_view_open_the_linked_note(env):
    import re

    _, out = env(["show", "--md", "forgetting"])
    [line] = re.findall(r"[→←] .+", out)  # what the Shortcut's Match Text step extracts
    assert line == "← Spaced repetition"
    _, out = env(["show", "--md", "-"], line)
    assert out.startswith("# Spaced repetition")
    _, out = env(["links", "--lines", "-"], "# Spaced repetition\n\nReview often.")  # a pasted note works too
    assert out.startswith("→ Forgetting curve")


def test_search_lines_star_lists_everything_newest_first_and_falls_back_to_fuzzy(env):
    _, out = env(["search", "--lines", "-"], "*")
    assert [ln.split(" · ")[0] for ln in out.splitlines()] == ["Ownership in Rust", "Forgetting curve", "Spaced repetition"]
    _, out = env(["search", "--lines", "rust", "owner"])  # not one substring, but every word matches
    assert out.startswith("Ownership in Rust")


def test_links_lines_with_backlinks_are_pickable(env):
    _, out = env(["links", "--lines", "-b", "-"], "Forgetting curve")
    assert out.startswith("← Spaced repetition · #learning · ")
    _, out = env(["show", "--md", "-"], out.splitlines()[0])
    assert out.startswith("# Spaced repetition")


def test_ssh_gate_allows_reading_and_capturing_only():
    assert ssh_gate_argv("~/.local/bin/sb search --lines -") == ["search", "--lines", "-"]
    assert ssh_gate_argv("export LANG=en_US.UTF-8; ~/.local/bin/sb capture --source phone") == [
        "capture", "--source", "phone"]
    assert ssh_gate_argv("sb -n show --md -") == ["-n", "show", "--md", "-"]
    for bad in ("~/.local/bin/sb rm -y x", "rm -rf ~", "sb sync", "sb", "sb 'unterminated"):
        with pytest.raises(SBError):
            ssh_gate_argv(bad)


def test_ssh_gate_runs_the_command(env, monkeypatch):
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "~/.local/bin/sb search --lines -")
    code, out = env(["_ssh_gate"], "curve")
    assert code == 0 and out.startswith("Forgetting curve")
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "~/.local/bin/sb rm -y curve")
    assert env(["_ssh_gate"])[0] == 1
