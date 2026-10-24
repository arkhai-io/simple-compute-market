"""API-credit negotiation hooks that need no database: term decoding.

The negotiation lifecycle against a real SQLite database is in
``tests/integration/test_sync_negotiation.py``.
"""

from __future__ import annotations

import pytest
from apicredits_storefront.domain_runtime import get_market_domain_contract
from arkhai_api_selling.negotiation import decode_terms as _decode_terms
from market_core.schemas import ProvisionTerms

_DOMAIN = get_market_domain_contract()


def test_decode_api_credits_message_terms_uses_domain_runtime() -> None:
    normalized = _decode_terms(
        _DOMAIN,
        ProvisionTerms(
            kind="api_credits.v1",
            version=1,
            payload={
                "quantity": "5",
                "key": {"mode": "existing", "key_id": "ak_existing"},
            },
        ),
    )

    assert normalized.decoded.quantity == 5
    assert normalized.decoded.key_mode == "existing"
    assert normalized.decoded.key_id == "ak_existing"


def test_normalize_api_credits_message_terms_rejects_foreign_terms() -> None:
    terms = ProvisionTerms(
        kind="compute.v1",
        version=1,
        payload={"duration_seconds": 60},
    )
    with pytest.raises(ValueError, match=r"api_credits\.v1"):
        _decode_terms(_DOMAIN, terms)


def test_normalize_api_credits_terms_rejects_unsupported_version() -> None:
    terms = ProvisionTerms(
        kind="api_credits.v1",
        version=2,
        payload={"quantity": 1, "key": {"mode": "new"}},
    )
    with pytest.raises(ValueError, match="version"):
        _decode_terms(_DOMAIN, terms)
