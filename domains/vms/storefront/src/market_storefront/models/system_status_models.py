"""The VM storefront's system status response.

Extends the common status model with what only this storefront reports. The
status route builds its response from the service's status dict, and a key the
response model does not declare never reaches a caller, so every VM-specific
status key is declared here.
"""

from __future__ import annotations

from typing import Any

from core_storefront.models.system_models import HealthResponse


class VmSystemStatusResponse(HealthResponse):
    """``GET /api/v1/system/status`` for the VM storefront."""

    #: Which listings bound before shapes carried a seller's close or pause,
    #: and to which shape-bearing successor.
    listing_identity_carryover: dict[str, Any] | None = None
    #: Every stored storefront pool override and the one state it is in:
    #: ``applied``, ``orphaned``, ``unknown``, ``site_unconfigured``, or
    #: ``inactive``.
    pool_overrides: list[dict[str, Any]] | None = None
