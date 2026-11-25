"""Command line interface. Every command (except init) syncs before it runs."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

from . import __version__
from .config import Config, SBError
from .note import Note, find_links
from .sync import SyncReport, Syncer, init_vault
from .vault import Vault

# -- output -----------------------------------------------------------------


def _style(code: str):
    def apply(text: str) -> str:
        if sys.stdout.isatty() and not os.environ.get("NO_COLOR"):
            return f"\033[{code}m{text}\033[0m"
        return text

    return apply


bold, dim, cyan, red = _style("1"), _style("2"), _style("36"), _style("31")


def fmt_note(note: Note) -> str:
    line = f"{dim(note.id or '-')}  {bold(note.title)}"
    if note.tags:
        line += "  " + cyan(" ".join("#" + t for t in note.tags))
    return line


def fmt_line(note: Note) -> str:
    """One plain line per note, title first: for phones and scripts. The trailing id
    makes the line itself a valid query, so a picked line can be passed straight back."""
    tags = " ".join("#" + t for t in note.tags)
    return " · ".join(part for part in (note.title, tags, note.id) if part)


def newest_first(notes: list[Note]) -> list[Note]:
    return sorted(notes, key=lambda n: n.id or "", reverse=True)


def stdin_query(query: list[str]) -> list[str]:
    """A query of `-` is read from stdin, so phones can send text without shell quoting."""
    if query != ["-"]:
        return query
    text = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return [line] if line else []


def info(msg: str) -> None:
    print(f"sb: {msg}", file=sys.stderr)


def report_sync(report: SyncReport, verbose: bool = False) -> None:
    for name in report.adopted:
        info(f"gave {name} an id and frontmatter")
    for title in report.conflicts:
        info(f"conflict: this note was also changed elsewhere. Your version is kept as '{title}'")
    if report.unreadable:
        info(f"skipped {len(report.unreadable)} note(s) encrypted with a different key: "
             + ", ".join(report.unreadable) + ". Re-save them from the machine that wrote them.")
    if report.network == "offline":
        info("offline (couldn't reach the remote); working locally")
    elif report.unpushed:
        info("push failed; your changes are committed locally and will push next time")
    moved = []
    if report.received:
        moved.append(f"{report.received} in")
    if report.pushed and report.sent:
        moved.append(f"{report.sent} out")
    if moved:
        info("synced (" + ", ".join(moved) + ")")
    elif verbose:
        info({"no-remote": "no remote configured; committed locally",
              "skipped": "offline mode; committed locally"}.get(report.network, "up to date"))


# -- helpers ----------------------------------------------------------------


NVIM_LUA = Path(__file__).parent / "nvim" / "sb.lua"


class App:
    def __init__(self, cfg: Config, sync: bool = True):
        self.cfg = cfg
        self.vault = Vault(cfg)
        self.syncer = Syncer(cfg, self.vault) if sync else None

    def sync(self, verbose: bool = False) -> None:
        if self.syncer:
            report_sync(self.syncer.sync(), verbose)

    def pick(self, query: list[str] | str, purpose: str = "note") -> Note:
        """Best-effort match; if several notes match (or no query was given), let the user choose."""
        from . import picker

        query = " ".join(query) if isinstance(query, list) else query
        by_id = {n.id: n for n in self.vault.notes()}
        for token in re.findall(r"\b\d{14}\b", query):
            if token in by_id:  # e.g. a line from `--lines` output
                return by_id[token]
        matches = self.vault.find(query) if query.strip() else list(self.vault.notes())
        if not matches:
            raise SBError(f"no note matches '{query}'" if query.strip() else "the vault has no notes yet")
        if len(matches) == 1 and query.strip():
            return matches[0]
        if picker.interactive():
            return picker.choose(matches, purpose, fmt_note)
        if not query.strip():
            raise SBError("which note? Give part of its title")
        listing = "\n".join("  " + fmt_note(n) for n in matches)
        raise SBError(f"'{query}' matches {len(matches)} notes, so be more specific:\n{listing}")

    def edit(self, path: Path, at_end: bool = False) -> None:
        cmd = list(self.cfg.editor)
        name = Path(cmd[0]).name
        if at_end and name in ("nvim", "vim", "vi"):
            cmd.append("+")
        env = dict(os.environ)
        if name == "nvim":
            # Load sb's link handling after the user's own config. Nothing to install per machine.
            cmd += ["-c", f"lua dofile({lua_string(str(NVIM_LUA))})"]
            env.update(SB_PYTHON=sys.executable, SB_NOTES_DIR=str(self.cfg.notes_dir))
        try:
            subprocess.run([*cmd, str(path)], env=env)
        except FileNotFoundError:
            raise SBError(f"editor not found: {cmd[0]} (set $SB_EDITOR or $EDITOR)") from None


def lua_string(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


# -- commands ---------------------------------------------------------------


def cmd_init(cfg: Config, args) -> None:
    report, key_created = init_vault(cfg, remote=args.remote, help_notes=not args.no_help)
    if key_created:
        info(f"created a new encryption key at {cfg.key_file}")
        info("BACK IT UP and copy it to your other machines. Without it the vault can't be read.")
    report_sync(report)
    count = len(Vault(cfg).notes())
    info(f"vault ready at {cfg.home} ({count} notes). Try: sb show welcome")


def cmd_new(app: App, args) -> None:
    title = " ".join(args.title)
    note = app.vault.create(title, tags=args.tag or [])
    assert note.path
    template = note.path.read_bytes()
    app.edit(note.path, at_end=True)
    if note.path.exists() and note.path.read_bytes() == template:
        note.path.unlink()
        info("nothing written; note discarded")
        return
    print(fmt_note(note))
    app.sync()


def read_capture_text(args) -> str:
    if args.text:
        return " ".join(args.text)
    if sys.stdin.isatty():
        info("type the note, then Ctrl-D")
    return sys.stdin.buffer.read().decode("utf-8", errors="replace")


def cmd_capture(app: App, args) -> None:
    """Save text without an editor: for phones, scripts and quick thoughts."""
    from .enrich import enrich, make_title, strip_filler

    text = strip_filler(read_capture_text(args))
    if not text:
        raise SBError("nothing to capture")
    inbox = os.environ.get("SB_CAPTURE_TAG", "inbox")
    base_tags = ([inbox] if inbox else []) + (args.tag or [])

    result = enrich(app.vault, text, exclude_tags=set(base_tags)) if not args.plain else None
    body_text = result.text if result else text
    tags = list(dict.fromkeys(base_tags + (result.tags if result else [])))
    title = args.title or make_title(text)

    body = f"\n# {title}\n\n{body_text}\n"
    if result and result.related:
        body += "\nRelated: " + " · ".join(f"[[{n.title}]]" for n in result.related) + "\n"
    if result and result.mentions:
        body += "\nMentions: " + " · ".join(f"[[{m}]]" for m in result.mentions) + "\n"
    extra = {"source": args.source} if args.source else {}

    if args.dry_run:
        print(Note(id="(new)", title=title, tags=tags, created="(now)", body=body, extra=extra).render(), end="")
        return
    app.vault.create(title, tags=tags, body=body, extra=extra)
    app.sync()

    summary = f"Saved “{title}”"
    if tags:
        summary += "  " + " ".join("#" + t for t in tags)
    if result and result.linked:
        summary += "\nlinked: " + ", ".join(n.title for n in result.linked)
    if result and result.related:
        summary += "\nrelated: " + ", ".join(n.title for n in result.related)
    if result and result.mentions:
        summary += "\nnew names: " + ", ".join(result.mentions)
    print(summary)


def cmd_edit(app: App, args) -> None:
    note = app.pick(args.query, "edit")
    assert note.path
    app.edit(note.path)
    app.sync()


def cmd_show(app: App, args) -> None:
    note = app.pick(stdin_query(args.query), "show")
    assert note.path
    if args.md:
        sys.stdout.write(reading_markdown(app.vault, note))
    else:
        sys.stdout.write(note.path.read_text(encoding="utf-8"))


def reading_markdown(vault: Vault, note: Note) -> str:
    """A note for reading on screens that don't know sb: no frontmatter, links in bold,
    and the tags and connections listed at the end."""
    from .note import LINK_RE, MD_LINK_RE

    def wiki(m: re.Match) -> str:
        inner = m.group(0)[2:-2]
        shown = inner.split("|", 1)[1] if "|" in inner else inner.split("#", 1)[0]
        return f"**{shown.strip()}**"

    body = MD_LINK_RE.sub(lambda m: "**" + m.group(0)[1:].split("](", 1)[0] + "**", note.body)
    body = LINK_RE.sub(wiki, body).strip("\n")
    if not body.lstrip().startswith("#"):
        body = f"# {note.title}\n\n{body}"
    meta = []
    if note.tags:
        meta.append("Tags: " + " ".join("#" + t for t in note.tags))
    targets = [vault.resolve_link(t) for t in note.links]
    out = list(dict.fromkeys(n.title for n in targets if n))
    if out:
        meta.append("Links to: " + ", ".join(out))
    back = [n.title for n in vault.backlinks(note)]
    if back:
        meta.append("Linked from: " + ", ".join(back))
    if note.created:
        meta.append(f"Created: {note.created}")
    return body + ("\n\n---\n\n" + "\n\n".join(meta) if meta else "") + "\n"


def cmd_path(app: App, args) -> None:
    print(app.pick(args.query, "path").path)


def cmd_ls(app: App, args) -> None:
    notes = [n for n, _ in app.vault.search(None, tags=args.tag or [])]
    for note in newest_first(notes) if args.lines else notes:
        print(fmt_line(note) if args.lines else fmt_note(note))


def cmd_search(app: App, args) -> None:
    query = " ".join(stdin_query(args.query)).strip()
    if args.lines:
        # Dictated queries arrive as "Rust ownership." and "*" means everything.
        query = query.strip(" .!?,").replace("*", "").strip()
        notes = [n for n, _ in app.vault.search(query or None, tags=args.tag or [])]
        if not notes and query:
            notes = app.vault.find(query)  # every word somewhere, or fuzzy
        for note in newest_first(notes):
            print(fmt_line(note))
        if not notes:
            info("no matches")
        return
    if not query and not args.tag:
        raise SBError("give a search term, a tag (-t), or both")
    results = app.vault.search(query, tags=args.tag or [])
    for note, line in results:
        print(fmt_note(note))
        if line:
            print("    " + dim(line[:120]))
    if not results:
        info("no matches")


def cmd_tags(app: App, args) -> None:
    for tag, count in app.vault.tags().items():
        print(f"{count:4d}  {cyan('#' + tag)}")


def cmd_links(app: App, args) -> None:
    note = app.pick(stdin_query(args.query), "links")
    if args.lines:
        targets = [app.vault.resolve_link(t) for t in note.links]
        out = list({n.id: n for n in targets if n}.values())
        back = app.vault.backlinks(note) if args.backlinks else []
        for other in out:
            print("→ " + fmt_line(other))
        for other in back:
            print("← " + fmt_line(other))
        return
    for target in note.links:
        linked = app.vault.resolve_link(target)
        print(f"→ {fmt_note(linked)}" if linked else red(f"→ [[{target}]] (no such note)"))
    if not note.links:
        info("no links")


def cmd_backlinks(app: App, args) -> None:
    note = app.pick(stdin_query(args.query), "backlinks")
    backlinks = app.vault.backlinks(note)
    for other in backlinks:
        print("← " + fmt_line(other) if args.lines else f"← {fmt_note(other)}")
    if not backlinks:
        info("no backlinks")


def cmd_rm(app: App, args) -> None:
    note = app.pick(args.query, "rm")
    assert note.path
    backlinks = app.vault.backlinks(note)
    if not args.yes:
        warning = f" ({len(backlinks)} note(s) link to it)" if backlinks else ""
        answer = input(f"Delete '{note.title}'{warning}? [y/N] ")
        if answer.strip().lower() not in ("y", "yes"):
            info("kept")
            return
    note.path.unlink()
    app.vault.refresh()
    info(f"deleted '{note.title}'")
    app.sync()


def cmd_graph(app: App, args) -> None:
    import shutil

    from .graph import Graph, render, stats

    graph = Graph.from_vault(app.vault)
    if args.stats:
        print(stats(graph))
        return

    footer, center = [], None
    if args.query:
        note = app.pick(args.query, "graph")
        index = next(i for i, n in enumerate(graph.notes) if n is note)
        keep = graph.neighborhood(index, args.depth)
        center = keep.index(index)
        graph = graph.subgraph(keep)
        footer.append(f"depth {args.depth} around '{note.title}'")
    elif not args.all:
        orphans = graph.orphans()
        if orphans and len(orphans) < len(graph.notes):
            graph = graph.subgraph([i for i in range(len(graph.notes)) if i not in set(orphans)])
            footer.append(f"{len(orphans)} orphans hidden (-a to show)")

    if args.size:
        width, height = (int(v) for v in args.size.lower().split("x"))
    else:
        term = shutil.get_terminal_size((100, 30))
        width, height = term.columns, term.lines - 1
    color = sys.stdout.isatty() and not os.environ.get("NO_COLOR") and not args.no_color
    print(render(graph, width, height, center=center, by=args.by,
                 labels=not args.no_labels, color=bool(color), footer=footer))


NVIM_SETUP = """\
-- sb: follow [[links]] even when you open notes with plain `nvim`.
-- (`sb edit` and `sb new` already do this; you only need it for direct use.)
vim.api.nvim_create_autocmd({{ "BufReadPre", "BufNewFile" }}, {{
  pattern = vim.fn.expand("{notes}") .. "/*.md",
  once = true,
  callback = function()
    local out = vim.fn.systemlist({{ vim.fn.expand("{sb}"), "_nvim" }})
    if vim.v.shell_error == 0 then
      vim.g.sb_python, vim.g.sb_notes_dir = out[2], out[3]
      dofile(out[1])
    end
  end,
}})"""


def cmd_nvim_setup(app: App, args) -> None:
    import shutil

    sb = shutil.which("sb") or "sb"
    if Path(sb).resolve() == Path("/usr/bin/sb").resolve():
        sb = "sb"
    sb = sb.replace(str(Path.home()), "~", 1)
    notes = str(app.cfg.notes_dir).replace(str(Path.home()), "~", 1)
    print(NVIM_SETUP.format(notes=notes, sb=sb))
    info("optional: paste this into your nvim config (e.g. ~/.config/nvim/init.lua)")


# -- internal commands used by sb.lua (no sync, machine-readable output) ------


def cmd_i_nvim(app: App, args) -> None:
    print(NVIM_LUA)
    print(sys.executable)
    print(app.cfg.notes_dir)


def cmd_i_resolve(app: App, args) -> None:
    note = app.vault.resolve_link(args.target)
    if note is None:
        raise SystemExit(3)  # "not found", distinct from a crash
    print(note.path)


def cmd_i_new(app: App, args) -> None:
    note = app.vault.create(args.title.strip())
    print(note.path)


def cmd_i_complete(app: App, args) -> None:
    for note in app.vault.notes():
        tags = " ".join("#" + t for t in note.tags)
        print(f"{note.title.replace(chr(9), ' ')}\t{tags}\t{note.path}")


def cmd_i_backlinks(app: App, args) -> None:
    """quickfix lines (path:line:col:text) for every link pointing at the note at PATH."""
    target = Path(args.path).resolve()
    note = next((n for n in app.vault.notes() if n.path.resolve() == target), None)
    if note is None:
        raise SystemExit(3)  # "not found", distinct from a crash
    for other in app.vault.backlinks(note):
        lines = other.path.read_text(encoding="utf-8").splitlines()
        for lnum, line in enumerate(lines, 1):
            for link, col in find_links(line):
                if app.vault.resolve_link(link) is note:
                    print(f"{other.path}:{lnum}:{col + 1}:{other.title}: {line.strip()}")
                    break


# -- shell completion ------------------------------------------------------------

BASH_COMPLETION = """\
# bash completion for sb. Installed by setup.sh; print it again with `sb completion bash`.
# Candidates come from sb itself, so this file never goes out of date.
_sb() {{
    local IFS=$'\\n'
    COMPREPLY=($(SB_PICKER=none {sb} _shell_complete "$COMP_CWORD" "${{COMP_WORDS[@]}}" 2>/dev/null))
}}
complete -o nosort -F _sb sb
"""


def cmd_completion(app: App, args) -> None:
    exe = os.path.abspath(sys.argv[0])
    sb = exe if Path(exe).name == "sb" else "sb"
    home = str(Path.home())
    sb = '"$HOME' + sb[len(home):] + '"' if sb.startswith(home + "/") else sb
    print(BASH_COMPLETION.format(sb=sb), end="")


NOTE_COMMANDS = {"cmd_edit", "cmd_show", "cmd_path", "cmd_links", "cmd_backlinks", "cmd_rm", "cmd_graph"}


def shell_candidates(cfg: Config, words: list[str], cword: int) -> list[str]:
    """Completions for words[cword], where words is the whole command line starting with `sb`."""
    cur = words[cword] if cword < len(words) else ""
    parser = build_parser()
    subparsers = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))

    def options(p: argparse.ArgumentParser) -> list[str]:
        return [o for a in p._actions for o in a.option_strings if o.startswith(cur)]

    sub = next((w for w in words[1:cword] if not w.startswith("-")), None)
    if sub is None:
        if cur.startswith("-"):
            return options(parser)
        return [a.dest for a in subparsers._choices_actions if a.dest.startswith(cur)]

    sp = subparsers.choices.get(sub)
    if sp is None:
        return []
    prev = words[cword - 1] if cword > 0 else ""
    if prev in ("-t", "--tag"):
        return [t for t in Vault(cfg).tags() if t.startswith(cur.lstrip("#"))]
    if prev == "--by":
        return [v for v in ("cluster", "tag") if v.startswith(cur)]
    if cur.startswith("-"):
        return options(sp)
    if sp.get_default("func").__name__ in NOTE_COMMANDS:
        return note_candidates(Vault(cfg), cur)
    return []


def note_candidates(vault: Vault, cur: str) -> list[str]:
    """Slugs (shell-friendly, and they resolve exactly). Prefix matches first, as shells expect;
    failing that, a single best-effort match. Several fuzzy matches are left to the picker."""
    notes = vault.notes()
    slug_count = Counter(n.slug for n in notes)
    name = {n.id: n.slug if slug_count[n.slug] == 1 else n.path.stem for n in notes}
    c = cur.casefold()
    hits = [name[n.id] for n in notes if name[n.id].startswith(c)]
    hits += [n.id for n in notes if c and n.id.startswith(c)]
    if hits or not c:
        return hits
    matches = vault.find(cur)
    return [name[matches[0].id]] if len(matches) == 1 else []


def cmd_sync(app: App, args) -> None:
    pass  # the sync before every command already did the work; main reports it verbosely


# -- parser -----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sb", description="Zettelkasten notes with encrypted git sync.")
    parser.add_argument("--version", action="version", version=f"sb {__version__}")
    parser.add_argument("-n", "--offline", action="store_true", help="don't touch the network this time")
    sub = parser.add_subparsers(metavar="command")

    def add(name, func, help, aliases=()):
        p = sub.add_parser(name, help=help, aliases=list(aliases), description=help)
        p.set_defaults(func=func)
        return p

    p = add("init", cmd_init, "create a vault, or clone one with --remote")
    p.add_argument("--remote", metavar="URL", help="git remote for the encrypted vault")
    p.add_argument("--no-help", action="store_true", help="don't add the how-to-use-sb notes")

    p = add("new", cmd_new, "create a note and open it in your editor", ["n"])
    p.add_argument("title", nargs="+")
    p.add_argument("-t", "--tag", action="append", help="tag (repeatable)")

    p = add("capture", cmd_capture, "save text as a note without an editor (reads stdin if no text)", ["c"])
    p.add_argument("text", nargs="*", help="the note; omit to read stdin")
    p.add_argument("-t", "--tag", action="append", help="extra tag (repeatable)")
    p.add_argument("--title", help="title (default: the first sentence)")
    p.add_argument("--source", help="recorded in frontmatter, e.g. phone")
    p.add_argument("--plain", action="store_true", help="no automatic links, tags or related notes")
    p.add_argument("--dry-run", action="store_true", help="print the note instead of saving it")
    p.set_defaults(presync=False)  # one sync after saving is enough: a new note can't conflict

    lines_help = "one plain line per note, title first, newest first (for phones and scripts)"
    commands = {}
    for name, func, help, aliases in (
        ("edit", cmd_edit, "open a note in your editor", ["e"]),
        ("show", cmd_show, "print a note", ["cat"]),
        ("path", cmd_path, "print a note's file path", []),
        ("links", cmd_links, "list what a note links to", []),
        ("backlinks", cmd_backlinks, "list notes that link to a note", ["bl"]),
    ):
        commands[name] = add(name, func, help, aliases)
        commands[name].add_argument(
            "query", nargs="*",
            help="id, title, part of a title, or a tag; leave empty to pick from all; - reads it from stdin",
        )
    commands["show"].add_argument("--md", action="store_true",
                                  help="plain markdown for reading: no frontmatter, links in bold, connections at the end")
    commands["links"].add_argument("--lines", action="store_true", help=lines_help)
    commands["links"].add_argument("-b", "--backlinks", action="store_true", help="with --lines: also notes linking here")
    commands["backlinks"].add_argument("--lines", action="store_true", help=lines_help)

    p = add("rm", cmd_rm, "delete a note")
    p.add_argument("query", nargs="*")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")

    p = add("ls", cmd_ls, "list notes", ["l"])
    p.add_argument("-t", "--tag", action="append", help="only notes with this tag (repeatable)")
    p.add_argument("--lines", action="store_true", help=lines_help)

    p = add("search", cmd_search, "search titles, tags and text", ["s"])
    p.add_argument("query", nargs="*", help="- reads it from stdin")
    p.add_argument("-t", "--tag", action="append", help="only notes with this tag (repeatable)")
    p.add_argument("--lines", action="store_true", help=lines_help + "; * or nothing lists all")

    p = add("graph", cmd_graph, "draw the knowledge graph in the terminal", ["g"])
    p.add_argument("query", nargs="*", help="center on this note and show its neighbourhood")
    p.add_argument("-d", "--depth", type=int, default=2, help="neighbourhood depth (default 2)")
    p.add_argument("--by", choices=["cluster", "tag"], default="cluster", help="what the colors mean")
    p.add_argument("-a", "--all", action="store_true", help="include orphans (notes with no links)")
    p.add_argument("--stats", action="store_true", help="hubs, orphans and broken links instead of a picture")
    p.add_argument("--size", metavar="WxH", help="canvas size (default: the terminal)")
    p.add_argument("--no-labels", action="store_true")
    p.add_argument("--no-color", action="store_true")

    add("tags", cmd_tags, "list tags with note counts")
    p = add("completion", cmd_completion, "print the bash completion script (setup.sh installs it)")
    p.add_argument("shell", choices=["bash"], nargs="?", default="bash")
    p.set_defaults(sync=False)
    add("nvim-setup", cmd_nvim_setup, "print an optional init.lua snippet for using plain nvim")

    # Internal commands for sb.lua: hidden from --help, and they skip sync.
    def internal(name, func, *arguments):
        p = sub.add_parser(name)
        p.set_defaults(func=func, sync=False)
        for arg in arguments:
            p.add_argument(arg)

    internal("_nvim", cmd_i_nvim)
    internal("_resolve", cmd_i_resolve, "target")
    internal("_new", cmd_i_new, "title")
    internal("_complete", cmd_i_complete)
    internal("_backlinks", cmd_i_backlinks, "path")
    add("sync", cmd_sync, "sync now (every command already syncs first)")
    return parser


# What a phone key restricted with `command="sb _ssh_gate"` may run: add and read, never delete.
GATE_COMMANDS = {"capture", "c", "search", "s", "show", "cat", "links", "backlinks", "bl", "ls", "l", "tags"}


def ssh_gate_argv(original: str) -> list[str]:
    """The sb arguments in an SSH command, if they're allowed. Nothing goes through a shell,
    so `;`, `$()` and friends are just text. Leading words (`export LANG=...;`) are ignored."""
    import shlex

    try:
        words = shlex.split(original)
    except ValueError:
        raise SBError("can't parse the command") from None
    start = next((i for i, w in enumerate(words) if os.path.basename(w) == "sb"), None)
    if start is None:
        raise SBError("only sb commands are allowed with this key")
    rest = words[start + 1:]
    sub = next((w for w in rest if not w.startswith("-")), None)
    if sub not in GATE_COMMANDS or any(w in ("-h", "--help") for w in rest[: rest.index(sub)]):
        raise SBError("this key may only run: capture, search, show, links, backlinks, ls, tags")
    return rest


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):
        # Over ssh from a phone there's often no locale; never die on an emoji.
        if (getattr(stream, "encoding", "") or "").lower() in ("ascii", "ansi_x3.4-1968"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if argv[:1] == ["_ssh_gate"]:
        try:
            argv = ssh_gate_argv(os.environ.get("SSH_ORIGINAL_COMMAND", ""))
        except SBError as exc:
            info(str(exc))
            return 1
    if argv[:1] == ["_shell_complete"]:
        # Bypass argparse: the words being completed may look like options.
        try:
            for candidate in shell_candidates(Config.from_env(), argv[2:], int(argv[1])):
                print(candidate)
        except Exception:
            pass  # never spew tracebacks into someone's prompt
        return 0

    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0

    cfg = Config.from_env()
    if args.offline:
        cfg = replace(cfg, offline=True)

    try:
        if args.func is cmd_init:
            cmd_init(cfg, args)
            return 0
        app = App(cfg, sync=getattr(args, "sync", True))
        if getattr(args, "presync", True):
            app.sync(verbose=args.func is cmd_sync)
        args.func(app, args)
        return 0
    except SBError as exc:
        info(str(exc))
        return 1
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
