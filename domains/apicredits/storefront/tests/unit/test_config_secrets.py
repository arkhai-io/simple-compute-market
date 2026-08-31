"""Role-scoped credits-service credential resolution."""

from __future__ import annotations

import pytest

from apicredits_storefront.utils import config


def test_credits_admin_key_reads_exact_regular_file(monkeypatch, tmp_path):
    secret_file = tmp_path / "credits-admin-key"
    secret_file.write_text("role-scoped-secret\n", encoding="utf-8")
    monkeypatch.setattr(
        config,
        "settings",
        {"credits.admin_key": "", "credits.admin_key_file": str(secret_file)},
    )

    assert config.credits_admin_key() == "role-scoped-secret"


def test_credits_admin_key_rejects_competing_sources(monkeypatch, tmp_path):
    secret_file = tmp_path / "credits-admin-key"
    secret_file.write_text("file-secret", encoding="utf-8")
    monkeypatch.setattr(
        config,
        "settings",
        {
            "credits.admin_key": "inline-secret",
            "credits.admin_key_file": str(secret_file),
        },
    )

    with pytest.raises(RuntimeError, match="mutually exclusive"):
        config.credits_admin_key()


def test_credits_admin_key_rejects_non_regular_file(monkeypatch, tmp_path):
    monkeypatch.setattr(
        config,
        "settings",
        {"credits.admin_key": "", "credits.admin_key_file": str(tmp_path)},
    )

    with pytest.raises(RuntimeError, match="regular file"):
        config.credits_admin_key()
