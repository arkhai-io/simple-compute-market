"""Whether a payment scenario's case stages have a dispute authority to file with.

The stages reach the authority their Agreement pins, which the registries
recommend; nothing here contacts it. MEDIATION.SERVICE_URL, a setting apart from
PAYMENTS, states that the run supplies one that accepts a filed case, and names
it. Blank, the default, means none is supplied, and each such stage reports a
blocked skip naming the setting rather than failing: no lane runs a mediation
authority, and the dispute authority a lane's registries recommend can never
answer.
"""

from __future__ import annotations

import pytest

from e2e_harness.settings import settings

_TARGET_KEY = "MEDIATION.SERVICE_URL"


def configured_mediation() -> str:
    """The configured mediation authority's URL, without a trailing slash, or a
    blocked skip naming the setting."""
    url = settings.get(_TARGET_KEY, "")
    if url is None or not str(url).strip():
        pytest.skip(f"blocked: {_TARGET_KEY} not configured")
    return str(url).strip().rstrip("/")
