"""Buyer evidence stays inside each test's owned profile directory."""

import pytest


@pytest.fixture(autouse=True)
def evidence_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ARKHAI_BUYER_PROFILE_STORE", str(tmp_path / "profiles.json"))
