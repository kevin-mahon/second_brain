"""Command line interface. Every command (except init) syncs before it runs."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from . import __version__
from .config import Config, SBError
from .note import Note
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


def info(msg: str) -> None:
    print(f"sb: {msg}", file=sys.stderr)


def report_sync(report: SyncReport, verbose: bool = False) -> None:
    for name in report.adopted:
        info(f"gave {name} an id and frontmatter")
    for title in report.conflicts:
        info(f"conflict: this note was also changed elsewhere. Your version is kept as '{title}'")
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


class App:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.vault = Vault(cfg)
        self.syncer = Syncer(cfg, self.vault)

    def sync(self, verbose: bool = False) -> None:
        report_sync(self.syncer.sync(), verbose)

    def pick(self, query: list[str] | str) -> Note:
        query = " ".join(query) if isinstance(query, list) else query
        matches = self.vault.find(query)
        if not matches:
            raise SBError(f"no note matches '{query}'")
        if len(matches) > 1:
            listing = "\n".join("  " + fmt_note(n) for n in matches)
            raise SBError(f"'{query}' matches {len(matches)} notes, so be more specific:\n{listing}")
        return matches[0]

    def edit(self, path: Path, at_end: bool = False) -> None:
        cmd = list(self.cfg.editor)
        if at_end and Path(cmd[0]).name in ("nvim", "vim", "vi"):
            cmd.append("+")
        try:
            subprocess.run([*cmd, str(path)])
        except FileNotFoundError:
            raise SBError(f"editor not found: {cmd[0]} (set $SB_EDITOR or $EDITOR)") from None


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


def cmd_edit(app: App, args) -> None:
    note = app.pick(args.query)
    assert note.path
    app.edit(note.path)
    app.sync()


def cmd_show(app: App, args) -> None:
    note = app.pick(args.query)
    assert note.path
    sys.stdout.write(note.path.read_text(encoding="utf-8"))


def cmd_path(app: App, args) -> None:
    print(app.pick(args.query).path)


def cmd_ls(app: App, args) -> None:
    for note, _ in app.vault.search(None, tags=args.tag or []):
        print(fmt_note(note))


def cmd_search(app: App, args) -> None:
    query = " ".join(args.query) if args.query else None
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
    note = app.pick(args.query)
    for target in note.links:
        linked = app.vault.resolve_link(target)
        print(f"→ {fmt_note(linked)}" if linked else red(f"→ [[{target}]] (no such note)"))
    if not note.links:
        info("no links")


def cmd_backlinks(app: App, args) -> None:
    note = app.pick(args.query)
    backlinks = app.vault.backlinks(note)
    for other in backlinks:
        print(f"← {fmt_note(other)}")
    if not backlinks:
        info("no backlinks")


def cmd_rm(app: App, args) -> None:
    note = app.pick(args.query)
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
        note = app.pick(args.query)
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

    for name, func, help, aliases in (
        ("edit", cmd_edit, "open a note in your editor", ["e"]),
        ("show", cmd_show, "print a note", ["cat"]),
        ("path", cmd_path, "print a note's file path", []),
        ("links", cmd_links, "list what a note links to", []),
        ("backlinks", cmd_backlinks, "list notes that link to a note", ["bl"]),
    ):
        add(name, func, help, aliases).add_argument("query", nargs="+", help="id, title, or part of a title")

    p = add("rm", cmd_rm, "delete a note")
    p.add_argument("query", nargs="+")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")

    p = add("ls", cmd_ls, "list notes", ["l"])
    p.add_argument("-t", "--tag", action="append", help="only notes with this tag (repeatable)")

    p = add("search", cmd_search, "search titles, tags and text", ["s"])
    p.add_argument("query", nargs="*")
    p.add_argument("-t", "--tag", action="append", help="only notes with this tag (repeatable)")

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
    add("sync", cmd_sync, "sync now (every command already syncs first)")
    return parser


def main(argv: list[str] | None = None) -> int:
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
        app = App(cfg)
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
