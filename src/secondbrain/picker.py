"""Choose one note from several: fzf (with a preview) if it's installed, else a numbered menu."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Callable

from .config import SBError
from .note import Note


def interactive() -> bool:
    return sys.stdin.isatty() and sys.stderr.isatty() and os.environ.get("SB_PICKER") != "none"


def choose(notes: list[Note], prompt: str, fmt: Callable[[Note], str]) -> Note:
    if os.environ.get("SB_PICKER", "fzf") == "fzf" and shutil.which("fzf"):
        return _fzf(notes, prompt)
    return _menu(notes, prompt, fmt)


def _fzf(notes: list[Note], prompt: str) -> Note:
    by_path = {str(n.path): n for n in notes}
    lines = []
    for note in notes:
        tags = " ".join("#" + t for t in note.tags)
        shown = f"{note.title}  \033[36m{tags}\033[0m" if tags else note.title
        lines.append(f"{shown}\t{note.path}")
    proc = subprocess.run(
        [
            "fzf", "--ansi", "--reverse", "--height=60%", "--cycle",
            "--delimiter=\t", "--with-nth=1",
            f"--prompt={prompt}> ",
            "--preview=cat {2}", "--preview-window=right,60%,wrap",
        ],
        input="\n".join(lines),
        stdout=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SBError("nothing picked")
    return by_path[proc.stdout.rstrip("\n").split("\t")[-1]]


def _menu(notes: list[Note], prompt: str, fmt: Callable[[Note], str]) -> Note:
    shown = notes
    while True:
        for i, note in enumerate(shown[:40], 1):
            print(f"{i:3d}) {fmt(note)}", file=sys.stderr)
        if len(shown) > 40:
            print(f"     … {len(shown) - 40} more; type to narrow", file=sys.stderr)
        try:
            answer = input(f"{prompt}: number, or text to narrow (Enter cancels): ").strip()
        except EOFError:
            answer = ""
        if not answer:
            raise SBError("nothing picked")
        if answer.isdigit() and 1 <= int(answer) <= min(len(shown), 40):
            return shown[int(answer) - 1]
        narrowed = [n for n in shown if answer.casefold() in (n.title + " " + " ".join(n.tags)).casefold()]
        if len(narrowed) == 1:
            return narrowed[0]
        if narrowed:
            shown = narrowed
        else:
            print(f"no match for '{answer}'", file=sys.stderr)
