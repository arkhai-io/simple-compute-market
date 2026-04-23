"""Unit tests for the install-role marker.

The marker is what lets `market install` produce different CLI surfaces
for buyers vs sellers without having two separate entrypoints. These
tests cover the get/set/clear roundtrip and the unknown-contents
safety path. They don't touch the real ~/.market directory — everything
goes through a temp path via monkeypatch.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from market import role


@pytest.fixture
def temp_role_file(tmp_path, monkeypatch):
    """Redirect the role module to a temp path for the duration of the test."""
    marker = tmp_path / "market_role"
    monkeypatch.setattr(role, "ROLE_FILE", marker)
    return marker


def test_get_role_returns_unset_when_marker_absent(temp_role_file):
    assert not temp_role_file.exists()
    assert role.get_role() == "unset"


def test_set_then_get_buyer_roundtrips(temp_role_file):
    path = role.set_role("buyer")
    assert path == temp_role_file
    assert temp_role_file.read_text().strip() == "buyer"
    assert role.get_role() == "buyer"


def test_set_then_get_seller_roundtrips(temp_role_file):
    role.set_role("seller")
    assert role.get_role() == "seller"


def test_set_overwrites_prior_role(temp_role_file):
    role.set_role("buyer")
    role.set_role("seller")
    assert role.get_role() == "seller"


def test_set_role_creates_parent_directory(tmp_path, monkeypatch):
    nested = tmp_path / "does" / "not" / "exist" / "role"
    monkeypatch.setattr(role, "ROLE_FILE", nested)
    role.set_role("buyer")
    assert nested.read_text().strip() == "buyer"


def test_set_role_rejects_unknown_value(temp_role_file):
    with pytest.raises(ValueError, match="Invalid role"):
        role.set_role("wholesaler")  # type: ignore[arg-type]
    # File not written.
    assert not temp_role_file.exists()


def test_get_role_returns_unset_when_file_is_corrupt(temp_role_file):
    """A corrupted marker should fall back to 'unset' so we never hide
    commands based on bogus contents."""
    temp_role_file.write_text("not_a_role\n")
    assert role.get_role() == "unset"


def test_get_role_trims_whitespace(temp_role_file):
    temp_role_file.write_text("  seller  \n\n")
    assert role.get_role() == "seller"


def test_clear_role_deletes_marker(temp_role_file):
    role.set_role("buyer")
    assert temp_role_file.exists()
    removed = role.clear_role()
    assert removed == temp_role_file
    assert not temp_role_file.exists()


def test_clear_role_is_idempotent(temp_role_file):
    assert not temp_role_file.exists()
    assert role.clear_role() is None


def test_get_role_returns_unset_on_unreadable_file(tmp_path, monkeypatch):
    """Permission error etc. shouldn't crash the CLI — treat as unset."""
    marker = tmp_path / "role"
    # Point at a directory, not a file — read_text() raises IsADirectoryError
    # which is an OSError subclass and so must be caught.
    marker.mkdir()
    monkeypatch.setattr(role, "ROLE_FILE", marker)
    assert role.get_role() == "unset"
