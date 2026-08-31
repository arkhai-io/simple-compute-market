"""Test-suite environment isolation for the storefront client."""

from __future__ import annotations

import os

import pytest

#: Constructing an HTTP client builds its transport eagerly from the ambient
#: proxy environment, before any request is made. A developer whose shell
#: configures a SOCKS proxy therefore cannot run these tests at all, for a
#: reason that has nothing to do with what they test.
_PROXY_VARIABLES = (
    "ALL_PROXY",
    "FTP_PROXY",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
)


@pytest.fixture(autouse=True)
def _no_ambient_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _PROXY_VARIABLES:
        for variant in (name, name.lower()):
            if variant in os.environ:
                monkeypatch.delenv(variant)
