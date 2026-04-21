"""
Unit tests for AnsibleService.

Covers: INI inventory parsing and lookup_host_ip.
subprocess-level methods (start_playbook, wait_for_playbook, check_connectivity)
are the external boundary — they are exercised in integration tests, not here.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from services.ansible_service import AnsibleService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service(inventory_text: str) -> tuple[AnsibleService, Path]:
    """Return an AnsibleService whose resolved_inventory_path points to a
    tmp file containing *inventory_text*."""
    settings = MagicMock()
    tmp = Path("/tmp/_test_inventory.ini")
    tmp.write_text(inventory_text, encoding="utf-8")
    settings.resolved_inventory_path = tmp
    settings.ansible_timeout_seconds = 30
    return AnsibleService(settings), tmp


# ---------------------------------------------------------------------------
# parse_inventory
# ---------------------------------------------------------------------------

INVENTORY_BASIC = """\
[kvm_hosts]
ww1 ansible_host=10.0.0.1 ansible_user=root ansible_port=22
ww2 ansible_host=10.0.0.2 ansible_user=root
"""

INVENTORY_WITH_COMMENTS = """\
# This is a comment
[production]
prod1 ansible_host=192.168.1.10

# Another comment
[staging]
staging1 ansible_host=192.168.1.20 some_var=some_val
"""

INVENTORY_EMPTY = ""

INVENTORY_ONLY_GROUPS = """\
[group_a]
[group_b]
"""


class TestParseInventory:
    def test_parses_host_name(self):
        svc, _ = _make_service(INVENTORY_BASIC)
        hosts = svc.parse_inventory()
        assert {h.name for h in hosts} == {"ww1", "ww2"}

    def test_parses_ansible_host(self):
        svc, _ = _make_service(INVENTORY_BASIC)
        hosts = {h.name: h for h in svc.parse_inventory()}
        assert hosts["ww1"].ansible_host == "10.0.0.1"
        assert hosts["ww2"].ansible_host == "10.0.0.2"

    def test_ansible_host_not_in_vars(self):
        """ansible_host is promoted to its own field and removed from vars."""
        svc, _ = _make_service(INVENTORY_BASIC)
        hosts = {h.name: h for h in svc.parse_inventory()}
        assert "ansible_host" not in hosts["ww1"].vars

    def test_remaining_vars_captured(self):
        svc, _ = _make_service(INVENTORY_BASIC)
        hosts = {h.name: h for h in svc.parse_inventory()}
        assert hosts["ww1"].vars["ansible_user"] == "root"
        assert hosts["ww1"].vars["ansible_port"] == "22"

    def test_skips_group_headers(self):
        svc, _ = _make_service(INVENTORY_BASIC)
        hosts = svc.parse_inventory()
        assert all("[" not in h.name for h in hosts)

    def test_skips_comment_lines(self):
        svc, _ = _make_service(INVENTORY_WITH_COMMENTS)
        hosts = svc.parse_inventory()
        assert all(not h.name.startswith("#") for h in hosts)

    def test_empty_inventory_returns_empty_list(self):
        svc, _ = _make_service(INVENTORY_EMPTY)
        assert svc.parse_inventory() == []

    def test_only_group_headers_returns_empty_list(self):
        svc, _ = _make_service(INVENTORY_ONLY_GROUPS)
        assert svc.parse_inventory() == []

    def test_search_filters_by_substring_case_insensitive(self):
        svc, _ = _make_service(INVENTORY_BASIC)
        results = svc.parse_inventory(search="WW1")
        assert len(results) == 1
        assert results[0].name == "ww1"

    def test_search_no_match_returns_empty(self):
        svc, _ = _make_service(INVENTORY_BASIC)
        assert svc.parse_inventory(search="nonexistent") == []

    def test_search_none_returns_all(self):
        svc, _ = _make_service(INVENTORY_BASIC)
        assert len(svc.parse_inventory(search=None)) == 2

    def test_host_without_vars(self):
        svc, _ = _make_service("barehost\n")
        hosts = svc.parse_inventory()
        assert len(hosts) == 1
        assert hosts[0].name == "barehost"
        assert hosts[0].ansible_host is None
        assert hosts[0].vars == {}

    def test_raises_file_not_found_when_inventory_missing(self):
        settings = MagicMock()
        settings.resolved_inventory_path = Path("/tmp/__nonexistent_inventory__.ini")
        svc = AnsibleService(settings)
        with pytest.raises(FileNotFoundError):
            svc.parse_inventory()

    def test_multiline_vars(self):
        svc, _ = _make_service(INVENTORY_WITH_COMMENTS)
        hosts = {h.name: h for h in svc.parse_inventory()}
        assert hosts["staging1"].vars["some_var"] == "some_val"


# ---------------------------------------------------------------------------
# lookup_host_ip
# ---------------------------------------------------------------------------

class TestLookupHostIp:
    def test_returns_ip_for_known_host(self):
        svc, _ = _make_service(INVENTORY_BASIC)
        assert svc.lookup_host_ip("ww1") == "10.0.0.1"
        assert svc.lookup_host_ip("ww2") == "10.0.0.2"

    def test_returns_none_for_unknown_host(self):
        svc, _ = _make_service(INVENTORY_BASIC)
        assert svc.lookup_host_ip("unknown") is None

    def test_returns_none_when_inventory_missing(self):
        settings = MagicMock()
        settings.resolved_inventory_path = Path("/tmp/__nonexistent__.ini")
        svc = AnsibleService(settings)
        assert svc.lookup_host_ip("ww1") is None

    def test_returns_none_for_host_without_ansible_host(self):
        svc, _ = _make_service("barehost ansible_user=root\n")
        assert svc.lookup_host_ip("barehost") is None
