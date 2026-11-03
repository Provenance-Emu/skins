"""Shared fixtures. Tests never read the real blocklist.json."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
import blocklist


@pytest.fixture(autouse=True)
def isolated_blocklist(tmp_path, monkeypatch):
    """Point blocklist.json at an empty temp file so a populated real one
    can't change test outcomes. Tests that need entries call `set_blocklist`."""
    path = tmp_path / "blocklist.json"
    path.write_text("[]\n")
    monkeypatch.setattr(blocklist, "BLOCKLIST_PATH", path)
    blocklist.clear_cache()
    yield path
    blocklist.clear_cache()


@pytest.fixture
def set_blocklist(isolated_blocklist):
    def _set(entries):
        blocklist.save_blocklist(entries, isolated_blocklist)
        return isolated_blocklist
    return _set


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """No test may open a socket. Everything that talks to a host is mocked, and
    deltastyles.com in particular must never see a test run."""
    import socket

    def refuse(self, *args, **kwargs):
        raise RuntimeError(f"test tried to open a network connection: {args}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: refuse(None, *a))
