"""The case stages' mediation target is blocked by name until one is configured.

The values are development fixtures, never used on any network.
"""

from __future__ import annotations

import pytest

from tests.e2e.roles.helpers import mediation


class _Settings:
    def __init__(self, url: object) -> None:
        self._url = url

    def get(self, key: str, default: object = None) -> object:
        assert key == "MEDIATION.SERVICE_URL"
        return self._url


@pytest.mark.parametrize("url", ["", "   ", None])
def test_no_mediation_target_blocks_naming_the_setting(monkeypatch, url) -> None:
    monkeypatch.setattr(mediation, "settings", _Settings(url))
    with pytest.raises(pytest.skip.Exception) as skipped:
        mediation.configured_mediation()
    assert "blocked: MEDIATION.SERVICE_URL not configured" in str(skipped.value)


def test_a_configured_mediation_target_is_its_url_without_a_trailing_slash(monkeypatch) -> None:
    monkeypatch.setattr(mediation, "settings", _Settings(" https://mediation.example/ "))
    assert mediation.configured_mediation() == "https://mediation.example"
