from __future__ import annotations

import os
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class SBError(Exception):
    """An error with a message meant for the user (no traceback)."""


@dataclass(frozen=True)
class Config:
    home: Path
    key_file: Path
    editor: tuple[str, ...]
    timeout: float
    offline: bool

    @property
    def notes_dir(self) -> Path:
        """Plaintext markdown notes. Ignored by git."""
        return self.home / "notes"

    @property
    def vault_dir(self) -> Path:
        """Encrypted copies of the notes. Committed and pushed."""
        return self.home / "vault"

    @property
    def state_file(self) -> Path:
        """Local record of what was last synced, used to skip unchanged notes."""
        return self.home / ".sb-state.json"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if env is None else env
        editor = env.get("SB_EDITOR") or env.get("EDITOR") or "nvim"
        return cls(
            home=Path(env.get("SB_HOME", "~/.sb")).expanduser(),
            key_file=Path(env.get("SB_KEY_FILE", "~/.second_brain_key")).expanduser(),
            editor=tuple(shlex.split(editor)),
            timeout=float(env.get("SB_SYNC_TIMEOUT", "8")),
            offline=env.get("SB_OFFLINE", "") not in ("", "0"),
        )
