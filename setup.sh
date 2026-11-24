#!/usr/bin/env bash
# One-shot setup for sb: installs the `sb` command globally (no venv to
# activate), makes sure it's on your PATH, and initialises your vault.
#
#   ./setup.sh                      install + create a new vault (or keep the existing one)
#   ./setup.sh --remote <git-url>   install + create/clone a vault synced to <git-url>
#   ./setup.sh --dev                also create .venv with test deps and run the tests
#
# Safe to re-run: it reinstalls sb and leaves an existing vault alone.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SB_HOME="${SB_HOME:-$HOME/.sb}"
KEY_FILE="${SB_KEY_FILE:-$HOME/.second_brain_key}"
REMOTE=""
DEV=0

usage() { sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --remote) REMOTE="${2:?--remote needs a git URL}"; shift 2 ;;
        --dev) DEV=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

say()  { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m!!  %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31mxx  %s\033[0m\n' "$*" >&2; exit 1; }

# -- 1. prerequisites ---------------------------------------------------------

say "Checking prerequisites"
command -v git >/dev/null || die "git is required (e.g. sudo apt install git)"
command -v python3 >/dev/null || die "python3 (>= 3.10) is required"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
    || die "python >= 3.10 is required (found $(python3 --version))"

if ! command -v uv >/dev/null && ! command -v pipx >/dev/null; then
    warn "Neither uv nor pipx is installed; one is needed to install sb as a global command."
    read -r -p "Install uv now from https://astral.sh/uv? [Y/n] " answer
    [[ "${answer:-y}" =~ ^[Yy] ]] || die "install uv or pipx, then re-run ./setup.sh"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
fi

if ! command -v nvim >/dev/null && [[ -z "${SB_EDITOR:-}${EDITOR:-}" ]]; then
    warn "nvim not found and \$EDITOR is unset; set SB_EDITOR or install neovim before using 'sb new'"
fi

# -- 2. install the sb command --------------------------------------------------

say "Installing sb (editable: changes in $REPO_DIR take effect immediately)"
if command -v uv >/dev/null; then
    uv tool install --quiet --force --editable "$REPO_DIR"
    BIN_DIR="$(uv tool dir --bin)"
else
    pipx install --force --editable "$REPO_DIR" >/dev/null
    BIN_DIR="${PIPX_BIN_DIR:-$HOME/.local/bin}"
fi

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
        warn "$BIN_DIR is not on your PATH; adding it to your shell config"
        if command -v uv >/dev/null; then uv tool update-shell; else pipx ensurepath; fi
        export PATH="$BIN_DIR:$PATH"
        NEW_SHELL=1
        ;;
esac
SB="$BIN_DIR/sb"
"$SB" --version >/dev/null || die "sb was installed but doesn't run; see the output above"
hash -r
if [[ "$(command -v sb)" != "$SB" ]]; then
    warn "'sb' on your PATH resolves to $(command -v sb), not $SB."
    warn "Put $BIN_DIR earlier in PATH, or add:  alias sb='$SB'"
fi

# Remove the old alias-style wrapper from earlier versions if it's lying around.
for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    if [[ -f "$rc" ]] && grep -q 'alias sb=.*sb\.sh' "$rc"; then
        warn "$rc still has an old 'alias sb=...sb.sh' line; remove it so it doesn't shadow the new sb"
    fi
done

# -- 3. vault -------------------------------------------------------------------

if [[ -d "$SB_HOME/.git" ]]; then
    if [[ -n "$REMOTE" ]]; then
        say "Vault exists at $SB_HOME; connecting it to $REMOTE"
        "$SB" init --remote "$REMOTE"
    else
        say "Vault already exists at $SB_HOME; syncing"
        "$SB" sync
    fi
else
    if [[ -n "$REMOTE" && ! -f "$KEY_FILE" ]]; then
        warn "No key at $KEY_FILE. If $REMOTE already holds a vault, copy the key from"
        warn "your other machine first, e.g.:  scp otherhost:.second_brain_key ~/ && chmod 600 $KEY_FILE"
        read -r -p "Continue anyway (only right if the remote is empty)? [y/N] " answer
        [[ "${answer:-n}" =~ ^[Yy] ]] || die "copy the key, then re-run ./setup.sh --remote $REMOTE"
    fi
    say "Creating vault at $SB_HOME"
    "$SB" init ${REMOTE:+--remote "$REMOTE"}
fi

# -- 4. optional dev environment ------------------------------------------------

if [[ $DEV -eq 1 ]]; then
    command -v uv >/dev/null || die "--dev needs uv"
    say "Creating dev environment in $REPO_DIR/.venv and running tests"
    (cd "$REPO_DIR" && uv venv --quiet --allow-existing .venv \
        && uv pip install --quiet -p .venv -e '.[dev]' && .venv/bin/pytest -q)
fi

# -- done -------------------------------------------------------------------------

say "Done. Try:  sb show welcome"
if [[ -z "$REMOTE" ]] && ! git -C "$SB_HOME" remote | grep -q .; then
    echo "    To sync between machines, create an empty private git repo and run:"
    echo "    ./setup.sh --remote <git-url>"
fi
if [[ "${NEW_SHELL:-0}" -eq 1 ]]; then
    echo "    Open a new terminal (or 'source' your shell rc) so 'sb' is on your PATH."
fi
