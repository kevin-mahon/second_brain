A Zettelkasten note taking CLI. Each note is a small markdown file holding
one idea, linked to other notes with `[[wikilinks]]`. It's built for
vim-like editors and syncs between machines through an encrypted git repo.

There is no database. The folder of markdown files *is* the index: sb
reads them every time it runs.

## How it stores things

```
~/.sb/notes/<id>-<slug>.md   plaintext notes you edit (git-ignored)
~/.sb/vault/<id>.enc         one encrypted file per note (committed + pushed)
~/.second_brain_key          encryption key (never committed, back it up!)
```

Every `sb` command syncs first: it encrypts locally changed notes, commits,
pulls, decrypts remote changes, and pushes. Commands that change a note sync
again afterwards. Only changed notes are re-encrypted. Titles are encrypted
too, so the remote only sees ids. If you're offline, sb notices within a few
seconds and keeps working.

If the same note was edited on two machines, the remote version wins and
yours is kept as a separate `... (conflict from <host>)` note.

## Features
- [X] Add notes
- [X] Markdown support, YAML frontmatter
- [X] Tagging
- [X] Search (titles, tags, full text)
- [X] `[[wikilinks]]` and backlinks
- [X] Sync (encrypted git)
- [X] Graph view (force-directed, braille + color in the terminal)
- [ ] Neovim integration (follow links, completion)
- [ ] Drawing support
- [ ] Export / Import

## Installation

```sh
git clone https://github.com/kevin-mahon/second_brain && cd second_brain
./setup.sh                              # local vault only
./setup.sh --remote <vault-git-url>     # vault synced through a private git repo
./setup.sh --dev                        # also create .venv and run the tests
```

`setup.sh` installs `sb` as a global command (`~/.local/bin/sb`, via
`uv tool` or `pipx`; it offers to install uv if neither is present), so
there's no virtualenv to activate. The install is editable, so changes in
this repo take effect immediately. It then creates, clones, or syncs your
vault. It's safe to re-run.

On another machine, copy `~/.second_brain_key` over **before** running
`./setup.sh --remote <same url>`.

Without cloning: `uv tool install git+https://github.com/kevin-mahon/second_brain`
(or `pipx install ...`), then `sb init [--remote <url>]`.

> Ubuntu ships an unrelated `/usr/bin/sb` (lrzsz, YMODEM). `~/.local/bin`
> normally comes first in `PATH`; setup warns if it doesn't.

## Usage

```
sb new <title> [-t tag]   create a note and open it in $SB_EDITOR / $EDITOR / nvim
sb edit <query>           edit a note (id, title, or any unique part of the title)
sb show <query>           print a note
sb ls [-t tag]            list notes
sb search <text> [-t tag] search titles, tags and text
sb tags                   tags with counts
sb links <query>          outgoing links (shows broken ones)
sb backlinks <query>      notes linking here
sb rm <query>             delete a note
sb path <query>           print a note's file path
sb graph [query] [-d N]   draw the network (or one note's neighbourhood)
sb graph --stats          hubs, orphans, broken links
sb sync                   sync (every command already does this)
sb -n <command>           skip the network this time (or SB_OFFLINE=1)
```

The vault seeds itself with notes explaining all of this. Start with
`sb show welcome`.

Environment: `SB_HOME` (default `~/.sb`), `SB_KEY_FILE`, `SB_EDITOR`,
`SB_SYNC_TIMEOUT` (seconds, default 8), `SB_OFFLINE`.
