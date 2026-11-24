import subprocess
from pathlib import Path

import pytest

from secondbrain.config import Config


@pytest.fixture(autouse=True)
def isolated_git(tmp_path, monkeypatch):
    """Keep the user's git config (signing, hooks, identity) out of the tests."""
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[user]\n\tname = sb test\n\temail = sb@example.invalid\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in ("SB_HOME", "SB_KEY_FILE", "SB_OFFLINE", "SB_EDITOR", "EDITOR"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def key_file(tmp_path) -> Path:
    return tmp_path / "key"


@pytest.fixture
def remote(tmp_path) -> str:
    path = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(path)], check=True)
    return str(path)


@pytest.fixture
def machine(tmp_path, key_file):
    """machine("a") -> a Config for a separate vault home sharing one key."""

    def make(name: str, offline: bool = False) -> Config:
        return Config(
            home=tmp_path / name / ".sb",
            key_file=key_file,
            editor=("true",),
            timeout=5,
            offline=offline,
        )

    return make
