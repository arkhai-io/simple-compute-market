"""The lanes' runner profile restates the double's committed fixture.

The runner reads its mediation target, the authority's identity a buyer's dispute
credential binds to, the buyer's token and the control token from
e2e-tests/config/config-payments-lane.yml; each restated value is held here to
the fixture it comes from. Every value is a public development value.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import yaml
from cryptography import x509

from mediation_lane_double.authority import load_authority
from mediation_lane_double.settings import PORT

from conftest import FIXTURES, committed_authority

_REPO = Path(__file__).resolve().parents[4]
_PROFILE = _REPO / "e2e-tests" / "config" / "config-payments-lane.yml"
# The double's leaf certificate, which the lane CA's generator in the controls
# project writes and the image serves.
_LEAF = _REPO / "tools" / "lane-double-controls" / "tls" / "mediation-double.pem"


def _mediation() -> dict:
    return yaml.safe_load(_PROFILE.read_text(encoding="utf-8"))["mediation"]


def test_the_runner_profile_restates_the_authority_fixture() -> None:
    authority = load_authority(FIXTURES / "authority.toml")
    mediation = _mediation()

    assert mediation["service_url"] == authority.origin
    assert mediation["account"] == authority.account
    assert mediation["record_key"] == authority.record_key
    assert mediation["lane_owned"] is True
    assert mediation["buyer_api_key"] == committed_authority()["accounts"]["buyer"]["token"]
    assert mediation["control_token"] == authority.control_token
    # The variable the harness hands the buyer's token over under, never one the
    # runner's own settings loader reads.
    assert not mediation["api_key_env"].startswith("ARKHAI_")


def test_the_target_is_a_name_the_certificate_covers_at_the_port_the_double_serves() -> None:
    leaf = x509.load_pem_x509_certificate(_LEAF.read_bytes())
    names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    url = urlsplit(_mediation()["service_url"])

    assert url.scheme == "https"
    assert url.hostname in names.get_values_for_type(x509.DNSName)
    assert url.port == PORT
