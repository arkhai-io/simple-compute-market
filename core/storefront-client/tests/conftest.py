"""Test-suite environment isolation for the storefront client."""

from __future__ import annotations

import os
from collections.abc import Iterator

import injected_time
import pytest
from injected_time import InjectedTime

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


#: The instant ``held_time`` holds the process time source at.
HELD_INSTANT = 1_000


@pytest.fixture
def held_time() -> Iterator[InjectedTime]:
    """The process time source, injected and held at ``HELD_INSTANT``.

    The client signs every request and judges every response's freshness by
    the source, so a test holding it knows each timestamp exactly.
    """
    before = injected_time.installed()
    source = InjectedTime(start=HELD_INSTANT)
    injected_time.install(source)
    yield source
    injected_time.install(before)
