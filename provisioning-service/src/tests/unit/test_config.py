"""Unit tests for the storefront-TOML admin-key fallback in config.py.

The seller compose mounts the storefront's TOML at
/etc/arkhai/storefront.toml. When `storefront_admin_key` isn't otherwise
set, we read `admin_api_key` from that file so the operator writes the
secret once.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def storefront_toml(tmp_path: Path):
    """Return a function that writes a TOML at a temp path and registers
    its location via STOREFRONT_TOML_PATH for the resolver to pick up.
    """
    saved = os.environ.get("STOREFRONT_TOML_PATH")
    target = tmp_path / "storefront.toml"

    def _write(contents: str) -> Path:
        target.write_text(contents)
        os.environ["STOREFRONT_TOML_PATH"] = str(target)
        return target

    yield _write

    if saved is None:
        os.environ.pop("STOREFRONT_TOML_PATH", None)
    else:
        os.environ["STOREFRONT_TOML_PATH"] = saved


class TestResolveStorefrontAdminKeyFromMount:
    def test_returns_key_when_toml_has_admin_api_key(self, storefront_toml):
        storefront_toml('admin_api_key = "hunter2"\n')
        from config import _resolve_storefront_admin_key_from_mount
        assert _resolve_storefront_admin_key_from_mount() == "hunter2"

    def test_returns_empty_when_admin_key_field_missing(self, storefront_toml):
        storefront_toml('other_field = "value"\n')
        from config import _resolve_storefront_admin_key_from_mount
        assert _resolve_storefront_admin_key_from_mount() == ""

    def test_returns_empty_when_admin_key_empty_string(self, storefront_toml):
        storefront_toml('admin_api_key = ""\n')
        from config import _resolve_storefront_admin_key_from_mount
        assert _resolve_storefront_admin_key_from_mount() == ""

    def test_malformed_toml_falls_back_silently(self, storefront_toml):
        storefront_toml("this = is = not valid TOML\n")
        from config import _resolve_storefront_admin_key_from_mount
        assert _resolve_storefront_admin_key_from_mount() == ""

    def test_no_file_returns_empty(self, monkeypatch, tmp_path):
        # Point the override at a non-existent path; default
        # /etc/arkhai/storefront.toml almost certainly doesn't exist in CI either.
        monkeypatch.setenv("STOREFRONT_TOML_PATH", str(tmp_path / "missing.toml"))
        from config import _resolve_storefront_admin_key_from_mount
        assert _resolve_storefront_admin_key_from_mount() == ""

    def test_override_path_takes_precedence_over_default(self, storefront_toml):
        # The fixture sets STOREFRONT_TOML_PATH to a tmp file with our
        # value; if the resolver hit /etc/arkhai/storefront.toml instead
        # we wouldn't see "from-override".
        storefront_toml('admin_api_key = "from-override"\n')
        from config import _resolve_storefront_admin_key_from_mount
        assert _resolve_storefront_admin_key_from_mount() == "from-override"
