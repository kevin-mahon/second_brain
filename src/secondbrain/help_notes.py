"""Notes that seed a fresh vault and explain how to use sb, from inside sb."""

from __future__ import annotations

from .vault import Vault

HELP_NOTES: list[tuple[str, list[str], str]] = [
    (
        "Welcome to sb",
        ["sb", "help"],
        """
# Welcome to sb

sb is a Zettelkasten in your terminal: small notes, each holding one idea,
linked together so ideas can find each other.

Start here, then follow the links:

- [[Zettelkasten in a nutshell]]: why the notes are small and linked
- [[Creating and editing notes]]: `sb new`, `sb edit`, what a note looks like
- [[Linking notes]]: wikilinks and backlinks
- [[Finding notes]]: listing, tags, and search
- [[The graph view]]: see the whole network in your terminal
- [[Using sb in Neovim]]: follow links with `gf`, backlinks, completion
- [[Sync and encryption]]: how your notes get to your other machines
- [[Setting up another machine]]

These are ordinary notes. Edit or delete them whenever you like:
`sb rm "Welcome to sb"`.
""",
    ),
    (
        "Zettelkasten in a nutshell",
        ["zettelkasten", "help"],
        """
# Zettelkasten in a nutshell

- **One idea per note.** Small notes can be combined; big ones can't.
- **Write in your own words.** A note is your thinking, not a copy.
- **Link as you write.** When an idea reminds you of another, link it:
  [[Linking notes]]. The links matter more than the folders, and sb has
  no folders.
- **Let structure grow.** Notes that collect many links become hubs.
  Tags are a loose second axis (see [[Finding notes]]).

Back to [[Welcome to sb]].
""",
    ),
    (
        "Creating and editing notes",
        ["sb", "help"],
        """
# Creating and editing notes

```
sb new Spaced repetition -t learning -t memory
sb edit spaced            # part of a title, a tag, or an id
sb e zett                 # several matches? pick one from a list
sb e                      # no query: pick from every note
sb show spaced            # print it without opening the editor
sb rm spaced
```

Matching is forgiving. Each word you type has to appear in the title, the
filename or a tag, and the best matches come first. As a last resort,
letters in order also match (`zkn` finds "Zettelkasten in a nutshell").
When more than one note matches, sb opens a picker: fzf with a preview if
it's installed, otherwise a numbered list you can narrow by typing.

Tab completion works too: `sb e spa<Tab>` becomes `sb e spaced-repetition`.

Each note is a markdown file in `~/.sb/notes/`, named `<id>-<slug>.md`.
It starts with a frontmatter block:

```
---
id: 20261124123000
title: Spaced repetition
tags: [learning, memory]
created: 2026-11-24 12:30
---
```

- `id` is a timestamp and never changes. Keep it if you rename a note.
- Change `title` and `tags` freely.
- If you quit the editor without writing anything, the new note is thrown away.

You can create files in `~/.sb/notes/` yourself, with any editor. On the
next `sb` run they get an id and frontmatter automatically.

The editor is `$SB_EDITOR`, then `$EDITOR`, then `nvim`.

Next: [[Linking notes]].
""",
    ),
    (
        "Linking notes",
        ["sb", "help", "links"],
        """
# Linking notes

Link to another note by writing its title in double brackets, for example
`[[Finding notes]]`. Variants:

- `[[Finding notes|how to search]]`: link with different display text
- `[[20261124123000]]`: link by id, which survives renames
- `[text](20261124123000-finding-notes.md)`: a plain markdown link. It
  works with stock `gf` in any editor and on GitHub, and still resolves
  by id if the file is renamed

A link matches a note by id, then title (case-insensitive), then filename,
then slug. Links inside `code` are ignored.

```
sb links "Linking notes"       # what this note links to (and broken links)
sb backlinks "Welcome to sb"   # which notes link here
```

Backlinks are how a Zettelkasten surprises you: they show ideas that
pointed at this one without you asking.

See also [[Zettelkasten in a nutshell]].
""",
    ),
    (
        "Finding notes",
        ["sb", "help", "search"],
        """
# Finding notes

```
sb ls                 # every note, oldest first
sb ls -t learning     # only notes tagged learning
sb tags               # every tag with how many notes use it
sb search forgetting  # titles, tags and full text
sb search -t help     # search within a tag
sb path "Finding"     # print the file path (handy for scripts and nvim)
```

There is no database. sb reads the markdown files every time it runs, so
what you see is always what's on disk.

Back to [[Welcome to sb]].
""",
    ),
    (
        "The graph view",
        ["sb", "help", "graph"],
        """
# The graph view

```
sb graph                  # the whole network (orphans hidden)
sb graph -a               # include orphans
sb graph spaced -d 1      # one note and its direct neighbours
sb graph --by tag         # color by tag instead of cluster
sb graph --stats          # hubs, orphans and broken links
```

Notes are placed by a force simulation: links pull notes together, all
notes push each other apart. Separate groups of notes are drawn apart.

- `◉` hub, `●` well linked, `•` linked, `·` orphan, `◎` the centre note
- Colors are clusters, notes that link mostly among themselves. The
  legend names each cluster after its best-connected note.
- The layout is stable: the same notes give the same picture.

`--stats` is worth checking now and then. Orphans and broken links are
where a Zettelkasten quietly decays. See [[Linking notes]].
""",
    ),
    (
        "Using sb in Neovim",
        ["sb", "help", "nvim"],
        """
# Using sb in Neovim

When `sb edit` or `sb new` opens nvim, it loads sb's link handling for
that session. Your nvim config isn't touched, so every machine with sb
installed gets it for free.

| key / command        | what it does                                           |
|----------------------|--------------------------------------------------------|
| `gf` or `<CR>`       | follow the link under the cursor (offers to create it) |
| `<C-o>`              | jump back (plain nvim)                                 |
| `gb`                 | backlinks to this note, in the quickfix list           |
| `[[` (insert mode)   | start a link and complete note titles                  |
| `:SbLink`            | pick a note and insert a link to it                    |
| `:SbNew [title]`     | create a note and open it                              |
| `:SbGraph [depth]`   | graph around this note in a terminal tab (`q` closes)  |

Jump around and edit as many notes as you like. When nvim exits, sb
syncs everything that changed. Both `[[wikilinks]]` and markdown links
work; see [[Linking notes]].

Opening notes with plain `nvim` instead? Run `sb nvim-setup` and paste
the snippet it prints into your init.lua. It's optional.
""",
    ),
    (
        "Sync and encryption",
        ["sb", "help", "sync"],
        """
# Sync and encryption

`~/.sb` is a git repository:

```
~/.sb/notes/          plaintext notes, never committed
~/.sb/vault/<id>.enc  one encrypted file per note, committed and pushed
```

**Every** `sb` command syncs first: it encrypts what changed locally,
commits, pulls, decrypts what changed remotely, and pushes. Commands
that change a note sync again afterwards.

- Only changed notes are re-encrypted.
- The encrypted files are named by id, and the title is encrypted too,
  so the remote never sees what your notes are about.
- Offline? sb waits a few seconds (`$SB_SYNC_TIMEOUT`, default 8), says
  so, and keeps working. Changes are committed locally and pushed next time.
- Skip the network for one command with `sb --offline ...`, or for a
  whole shell with `SB_OFFLINE=1`.
- sb never prompts for SSH passwords. Use a key with ssh-agent.

**Conflicts:** if one note was edited on two machines between syncs, the
remote version wins and yours is kept as a new note titled
`... (conflict from <host>)`. Merge the two by hand, then `sb rm` the
copy.

**The key** lives at `~/.second_brain_key` (or `$SB_KEY_FILE`). It is
never committed. Lose it and the vault can't be decrypted, so back it up.

See [[Setting up another machine]].
""",
    ),
    (
        "Setting up another machine",
        ["sb", "help", "sync"],
        """
# Setting up another machine

1. Install sb: `pipx install git+<your sb repo url>` (or `uv tool install`).
2. Copy the key over, privately:
   `scp home:~/.second_brain_key ~/ && chmod 600 ~/.second_brain_key`
3. Clone the vault: `sb init --remote <your vault remote>`

On the first machine, connect a remote the same way: create an empty
private repo (on GitHub, or a bare repo on a home server:
`git init --bare ~/sb-vault.git`) and run `sb init --remote <url>`.

How sync works: [[Sync and encryption]].
""",
    ),
]


def write_help_notes(vault: Vault) -> None:
    for title, tags, body in HELP_NOTES:
        vault.create(title, tags=tags, body=body)
