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
- [X] `[[wikilinks]]`, markdown links, and backlinks
- [X] Sync (encrypted git)
- [X] Graph view (force-directed, braille + color in the terminal)
- [X] Neovim integration (`gf` on links, backlinks, `[[` completion), no nvim config needed
- [ ] iOS App

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
sb edit [query]           edit a note; several matches (or none given) open a picker
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

### Neovim

`sb edit` and `sb new` load `src/secondbrain/nvim/sb.lua` into nvim for that
session (after your own config), so it works on every machine sb is
installed on:

- `gf` / `<CR>` follow `[[link]]` or `[text](note.md)` (offers to create missing notes)
- `gb` backlinks to the quickfix list; `[[` in insert mode completes titles
- `:SbLink`, `:SbNew`, `:SbBacklinks`, `:SbGraph`

If you open notes with plain `nvim`, `sb nvim-setup` prints an optional
init.lua snippet.

### Capture (no editor)

```
sb capture "some thought"            # or pipe text on stdin
sb capture --dry-run "..."           # preview
```

Captured text is linked to your vault automatically, on the local machine:
mentions of note titles become `[[links]]`, tags are suggested from similar
notes, plus `Related:` and `Mentions:` lines and a title taken from the first
sentence. Captures are tagged `#inbox` (change with `SB_CAPTURE_TAG`). Use
`--plain` to skip all of this.

## One vault server, every machine

The vault lives on one always-on home machine (the "server"). It holds a bare
git repo of the encrypted vault and also takes captures from your phone.

**1. On the server, once:**

```sh
git init --bare -b main ~/sb-vault.git
git clone https://github.com/kevin-mahon/second_brain ~/second_brain
cd ~/second_brain && ./setup.sh --remote ~/sb-vault.git   # the server's own vault
```

The first machine to run `setup.sh` creates the key (`~/.second_brain_key`). If
you already have one, copy it to the server *before* running setup.

**2. On every other machine:** add an SSH alias, so that if the server's address
changes you only edit one line per machine:

```
# ~/.ssh/config
Host sbvault
    HostName <server-ip-or-dns-name>
    User <your-user>
```

Then copy the key over and run setup:

```sh
scp sbvault:.second_brain_key ~/ && chmod 600 ~/.second_brain_key
./setup.sh --remote sbvault:sb-vault.git
```

To repoint an existing vault later: `sb init --remote sbvault:sb-vault.git`.

The server only ever stores encrypted notes in git. The plaintext `notes/`
folder exists only on machines you edit on, including the server itself if it
takes captures.

## iPhone: dictate a note (iOS Shortcut)

Your phone needs no app and no key. It runs `sb capture` on the server over
SSH; the server enriches, encrypts and pushes the note.

**Shortcut "Capture to sb"** (Shortcuts app → **+**):

1. Tap **ⓘ** (Details) → turn on **Show in Share Sheet**, so you can share
   text from any app.
2. Add **Receive** *Text* input from *Share Sheet*. If there's no input:
   **Continue**.
3. Add **If** *Shortcut Input* **has any value**:
   - **Set variable** `Note` to *Shortcut Input*
   - **Otherwise:** **Dictate Text** (Stop Listening: *After Pause*), then
     **Set variable** `Note` to *Dictated Text*
   - **End If**
4. Add **Run Script Over SSH**:
   - Script: `export LANG=en_US.UTF-8; ~/.local/bin/sb capture --source phone`
   - Host: your server's address, Port `22`, User: your login
   - Authentication: **SSH Key**. Shortcuts generates an ed25519 key; tap it
     → **Share Public Key**, and append that line to the server's
     `~/.ssh/authorized_keys`.
   - Input: the `Note` variable. It reaches `sb` on stdin, so quotes and
     emoji in your dictation can't break the command.
5. Add **Show Notification** with *Shell Script Result*. It shows something
   like `Saved "…" #inbox #learning`, plus what got linked.

"Hey Siri, capture to sb" then works hands-free.

**Optional "Search sb" Shortcut:** **Ask for Input** (Text) → **Run Script Over
SSH** with script `read -r q; ~/.local/bin/sb search "$q"` and Input *Provided
Input* → **Quick Look** on *Shell Script Result*.

**Hardening (recommended, since SSH is exposed to the internet):**
- Use key-only logins on the server: set `PasswordAuthentication no` in
  `/etc/ssh/sshd_config`.
- Restrict the phone's key to capturing only, so a lost phone can only add
  notes. Prefix its line in `authorized_keys` like this (the Shortcut's
  script is then ignored, and the dictation still arrives on stdin):

  ```
  command="LANG=en_US.UTF-8 ~/.local/bin/sb capture --source phone",no-pty,no-port-forwarding,no-agent-forwarding ssh-ed25519 AAAA... shortcuts
  ```

  The search Shortcut would then need its own, unrestricted key.

### Finding the note you mean

Every command that takes a note (`edit`, `show`, `rm`, `links`,
`backlinks`, `path`, `graph`) does best-effort matching on titles, tags
and ids. If more than one note matches, or you give no query, it opens a
picker: fzf with a preview if installed (`SB_PICKER=builtin` for a
numbered menu instead). Tab completion is installed by `setup.sh` into
`~/.local/share/bash-completion/completions/sb`.

The vault seeds itself with notes explaining all of this. Start with
`sb show welcome`.

Environment: `SB_HOME` (default `~/.sb`), `SB_KEY_FILE`, `SB_EDITOR`,
`SB_SYNC_TIMEOUT` (seconds, default 8), `SB_OFFLINE`.
