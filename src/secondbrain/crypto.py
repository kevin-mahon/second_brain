"""Per-note encryption. The key never leaves the machine and is never committed."""

from __future__ import annotations

import json
import os

from cryptography.fernet import Fernet, InvalidToken

from .config import Config, SBError


def key_exists(cfg: Config) -> bool:
    return cfg.key_file.exists()


def create_key(cfg: Config) -> None:
    cfg.key_file.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(cfg.key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(Fernet.generate_key())


class Cipher:
    def __init__(self, cfg: Config):
        if not cfg.key_file.exists():
            raise SBError(
                f"no encryption key at {cfg.key_file}. Copy it over from a machine that "
                "already has your vault (the key is never stored in git)."
            )
        try:
            self._fernet = Fernet(cfg.key_file.read_bytes().strip())
        except ValueError:
            raise SBError(f"{cfg.key_file} is not a valid key") from None

    def encrypt(self, name: str, text: str) -> bytes:
        # The filename is encrypted along with the content, so titles never
        # appear in the git repo and renames sync between machines.
        payload = json.dumps({"v": 1, "name": name, "text": text}, ensure_ascii=False)
        return self._fernet.encrypt(payload.encode("utf-8")) + b"\n"

    def decrypt(self, blob: bytes) -> tuple[str, str]:
        try:
            data = json.loads(self._fernet.decrypt(blob.strip()))
        except InvalidToken:
            raise SBError(
                "could not decrypt the vault: your key doesn't match the one these notes "
                "were encrypted with"
            ) from None
        return data["name"], data["text"]
