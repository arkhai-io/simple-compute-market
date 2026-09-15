"""Routine entrypoint for the opt-in rootless cryptsetup CLI qualification."""

from __future__ import annotations

import os

import pytest

import cryptsetup_keyring_filter_harness as harness


@pytest.mark.skipif(
    os.environ.get("ARKHAI_RUN_CRYPTSETUP_KEYRING_HARNESS") != "1",
    reason="set ARKHAI_RUN_CRYPTSETUP_KEYRING_HARNESS=1 for the real CLI lane",
)
def test_real_cli_disables_request_key_for_luks2_passphrase_verification():
    result = harness.qualify(harness.cryptsetup_binary())
    wrong_key = result["results"]["wrong_key_with_disable_keyring"]

    assert {key: result[key] for key in (
        "schema",
        "qualified",
        "cryptsetup_version",
        "request_key_syscall",
    )} == {
        "schema": "arkhai.cryptsetup-keyring-filter-qualification.v1",
        "qualified": True,
        "cryptsetup_version": "2.4.3",
        "request_key_syscall": 249,
    }
    assert result["results"]["without_disable_keyring"] == {
        "kind": "signal",
        "code": 31,
    }
    assert result["results"]["with_disable_keyring"] == {
        "kind": "exit",
        "code": 0,
    }
    assert wrong_key["kind"] == "exit"
    assert isinstance(wrong_key["code"], int)
    assert wrong_key["code"] > 0
