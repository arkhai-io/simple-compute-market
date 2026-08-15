from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from market_identity import Ed25519Signer, TrustedIdentitySet
from registry_client import FilterSpecResponse

from core_buyer import (
    BuyConfig,
    BuyConstraints,
    BuyResult,
    NegotiationResult,
    RegistryAuthority,
    explain_registry_query,
    query_registry_for_matches_multi,
    run_buy,
)
from core_buyer.orchestration import make_publisher_trust_resolver


def _trusted(*signers: Ed25519Signer) -> TrustedIdentitySet:
    return TrustedIdentitySet(identities=tuple(signer.identity for signer in signers))


def _authority(name: str, *signers: Ed25519Signer) -> RegistryAuthority:
    return RegistryAuthority(authority=name, principals=_trusted(*signers))


def _config() -> BuyConfig:
    signer = Ed25519Signer(b"\x01" * 32)
    registry = Ed25519Signer(b"\x05" * 32)
    return BuyConfig(
        registry_urls=["http://registry"],
        registry_authorities={"http://registry": _authority("registry", registry)},
        principal=signer.identity,
        buyer_profile_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        signer=signer,
    )


def test_buy_config_rejects_signer_principal_mismatch() -> None:
    owner = Ed25519Signer(b"\x03" * 32)
    other = Ed25519Signer(b"\x04" * 32)

    with pytest.raises(ValueError, match="does not match"):
        BuyConfig(
            registry_urls=[],
            registry_authorities={},
            principal=owner.identity,
            buyer_profile_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
            signer=other,
        )


def test_buy_config_requires_exact_registry_authority_set() -> None:
    buyer = Ed25519Signer(b"\x0d" * 32)
    registry = Ed25519Signer(b"\x0e" * 32)
    with pytest.raises(ValueError, match="exactly match"):
        BuyConfig(
            registry_urls=["http://registry"],
            registry_authorities={"http://other": _authority("other", registry)},
            principal=buyer.identity,
            buyer_profile_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
            signer=buyer,
        )


def test_buy_config_repr_does_not_expose_signer_or_api_key() -> None:
    config = _config()
    config.registry_api_keys["http://registry"] = "private-bearer"
    rendered = repr(config)
    assert "private-bearer" not in rendered
    assert "signer=" not in rendered


def test_run_buy_returns_no_matches_without_invoking_hooks() -> None:
    with patch(
        "core_buyer.orchestrator.query_registry_for_matches_multi",
        return_value=[],
    ):
        result = run_buy(
            config=_config(),
            constraints=BuyConstraints(),
            provision={"duration_seconds": 3600},
            negotiate=lambda _matches, _emit: (_ for _ in ()).throw(AssertionError()),
            settle=lambda _negotiation, _emit: (_ for _ in ()).throw(AssertionError()),
        )

    assert result.status == "no_matches"


def test_run_buy_composes_injected_negotiate_and_settle_hooks() -> None:
    matches = [
        {"listing_id": "L1", "seller": "http://seller"},
        {"listing_id": "L2", "seller": "http://other"},
    ]
    events: list[tuple[str, dict]] = []

    def negotiate(candidate_matches, emit) -> NegotiationResult:
        emit("domain_negotiate", {"count": len(candidate_matches)})
        return NegotiationResult(
            match=candidate_matches[0],
            outcome={"negotiation_id": "N1", "amount": 10},
            attempts=[{"listing_id": "L1", "status": "agreed"}],
        )

    def settle(negotiation, emit) -> BuyResult:
        emit("domain_settle", {"listing_id": negotiation.match["listing_id"]})
        return BuyResult(
            status="ready",
            negotiation_id=negotiation.outcome["negotiation_id"],
            seller_url=negotiation.match["seller"],
            agreed_amount=negotiation.outcome["amount"],
            attempts=negotiation.attempts,
        )

    signer = Ed25519Signer(b"\x02" * 32)
    result = run_buy(
        config=BuyConfig(
            registry_urls=["http://registry"],
            registry_authorities={
                "http://registry": _authority(
                    "registry",
                    Ed25519Signer(b"\x06" * 32),
                )
            },
            principal=signer.identity,
            buyer_profile_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
            signer=signer,
            aggregation_policy="domain-policy",
        ),
        constraints=BuyConstraints(max_price=100),
        provision={"duration_seconds": 3600},
        negotiate=negotiate,
        settle=settle,
        matches=matches,
        max_matches_to_try=1,
        on_event=lambda name, body: events.append((name, body)),
    )

    assert result.status == "ready"
    assert result.negotiation_id == "N1"
    assert result.seller_url == "http://seller"
    assert (
        "aggregated",
        {"policy": "domain-policy", "match_count_after_cap": 1},
    ) in events
    assert ("domain_negotiate", {"count": 1}) in events
    assert ("domain_settle", {"listing_id": "L1"}) in events


def test_query_registry_for_matches_multi_dedupes_first_seen_listing() -> None:
    buyer = Ed25519Signer(b"\x07" * 32)
    first = Ed25519Signer(b"\x08" * 32)
    second = Ed25519Signer(b"\x09" * 32)
    authorities = {
        "http://r1": _authority("registry-ha", first),
        "http://r2": _authority("registry-ha", second),
    }

    def query(url, *_args, **kwargs):
        assert kwargs["signer"] is buyer
        assert kwargs["registry_authority"] == authorities[url]
        if url == "http://r1":
            return [{"listing_id": "L1", "seller": "http://r1"}]
        return [
            {"listing_id": "L1", "seller": "http://r2"},
            {"listing_id": "L2", "seller": "http://r2"},
        ]

    with patch(
        "core_buyer.orchestrator._query_registry_for_matches",
        side_effect=query,
    ):
        result = query_registry_for_matches_multi(
            ["http://r1", "http://r2"],
            signer=buyer,
            registry_authorities=authorities,
        )

    assert result == [
        {
            "listing_id": "L1",
            "seller": "http://r1",
            "source_registry_url": "http://r1",
            "source_registry_authority": "registry-ha",
        },
        {
            "listing_id": "L2",
            "seller": "http://r2",
            "source_registry_url": "http://r2",
            "source_registry_authority": "registry-ha",
        },
    ]


def test_registry_query_compiles_resource_and_uses_exact_authority_pin() -> None:
    buyer = Ed25519Signer(b"\x0a" * 32)
    registry = Ed25519Signer(b"\x0b" * 32)
    calls: list[dict] = []

    class FakeClient:
        def __init__(self, base_url, **kwargs):
            calls.append({"base_url": base_url, **kwargs})

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def get_filter_spec(self):
            return FilterSpecResponse.from_dict(
                {
                    "version": 1,
                    "etag": "filter-v1",
                    "filters": [
                        {
                            "name": "region",
                            "path": "$.offer_resource.region",
                            "op": "in",
                            "value_type": "string",
                        }
                    ],
                }
            )

        def list_listings(self, **kwargs):
            calls.append({"listing_args": kwargs})

            class Listing:
                def to_dict(self):
                    return {
                        "listing_id": "L1",
                        "publisher_principals": _trusted(registry).model_dump(
                            mode="json"
                        ),
                    }

            return type("Response", (), {"listings": [Listing()]})()

    with patch("core_buyer.orchestrator.SyncRegistryClient", FakeClient):
        result = explain_registry_query(
            ["http://registry/"],
            signer=buyer,
            registry_authorities={"http://registry": _authority("registry", registry)},
            resource_query="region=eu",
            limit=7,
            api_keys={"http://registry": "optional-bearer"},
        )

    assert result.listings[0]["publisher_principals"] == _trusted(registry).model_dump(
        mode="json"
    )
    assert [plan.to_dict() for plan in result.query_plans] == [
        {
            "registry_url": "http://registry",
            "filter_spec": {
                "version": 1,
                "etag": "filter-v1",
                "schema_id": None,
                "schema_version": None,
            },
            "canonical_resource_query": "region=eu",
            "registry_parameters": {"region": "eu"},
        }
    ]
    expected_client = {
        "base_url": "http://registry",
        "signer": buyer,
        "caller_role": "buyer",
        "expected_registries": _trusted(registry),
        "registry_authority": "registry",
        "timeout": 30.0,
        "api_key": "optional-bearer",
    }
    assert calls[0] == expected_client
    assert calls[1] == expected_client
    assert calls[2]["listing_args"] == {
        "status": "open",
        "limit": 7,
        "offset": 0,
        "etag": "filter-v1",
        "region": "eu",
    }


def test_multi_registry_query_rejects_partial_vocabulary_before_listing() -> None:
    buyer = Ed25519Signer(b"\x0a" * 32)
    registries = {
        "http://r1": Ed25519Signer(b"\x0b" * 32),
        "http://r2": Ed25519Signer(b"\x0c" * 32),
    }
    list_calls = 0

    class FakeClient:
        def __init__(self, base_url, **_kwargs):
            self.base_url = base_url

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

        def get_filter_spec(self):
            field = "region" if self.base_url == "http://r1" else "gpu_model"
            return FilterSpecResponse.from_dict(
                {
                    "version": 1,
                    "etag": f"{field}-v1",
                    "filters": [
                        {
                            "name": field,
                            "path": f"$.offer_resource.{field}",
                            "op": "in",
                            "value_type": "string",
                        }
                    ],
                }
            )

        def list_listings(self, **_kwargs):
            nonlocal list_calls
            list_calls += 1
            raise AssertionError("listing request occurred before complete compilation")

    authorities = {
        url: _authority("registry", signer) for url, signer in registries.items()
    }
    with (
        patch("core_buyer.orchestrator.SyncRegistryClient", FakeClient),
        pytest.raises(RuntimeError, match="not valid for registry http://r2"),
    ):
        query_registry_for_matches_multi(
            list(registries),
            signer=buyer,
            registry_authorities=authorities,
            resource_query="region=eu",
        )

    assert list_calls == 0


def test_publisher_trust_resolver_accepts_signed_rotation_without_mutating_listing() -> (
    None
):
    old = Ed25519Signer(b"\x1a" * 32)
    replacement = Ed25519Signer(b"\x1b" * 32)
    listing = {
        "listing_id": "L1",
        "publisher_id": 7,
        "storefront_url": "http://seller",
        "source_registry_url": "http://registry",
        "source_registry_authority": "registry",
        "publisher_principals": _trusted(old).model_dump(mode="json"),
        "offer_resource": {"price": 10},
    }
    refreshed = {
        **listing,
        "publisher_principals": _trusted(replacement).model_dump(mode="json"),
        "offer_resource": {"price": 999},
    }
    updates: list[tuple[str, dict]] = []
    with patch(
        "core_buyer.orchestration.fetch_listing_dict",
        return_value=refreshed,
    ):
        resolve = make_publisher_trust_resolver(
            config=_config(),
            listing=listing,
            on_update=lambda stage, body: updates.append((stage, body)),
        )
        assert resolve() == _trusted(replacement)

    assert listing["offer_resource"] == {"price": 10}
    assert updates == [
        (
            "publisher_trust_refreshed",
            {
                "listing_id": "L1",
                "publisher_id": 7,
                "publisher_principals": _trusted(replacement).model_dump(mode="json"),
                "source_registry_url": "http://registry",
                "source_registry_authority": "registry",
            },
        )
    ]


def test_publisher_trust_resolver_rejects_forged_registry_refresh() -> None:
    publisher = Ed25519Signer(b"\x1c" * 32)
    listing = {
        "listing_id": "L1",
        "publisher_id": 7,
        "storefront_url": "http://seller",
        "source_registry_url": "http://registry",
        "source_registry_authority": "registry",
        "publisher_principals": _trusted(publisher).model_dump(mode="json"),
    }
    updates: list[tuple[str, dict]] = []
    with patch(
        "core_buyer.orchestration.fetch_listing_dict",
        side_effect=RuntimeError("invalid registry response: wrong_principal"),
    ):
        resolve = make_publisher_trust_resolver(
            config=_config(),
            listing=listing,
            on_update=lambda stage, body: updates.append((stage, body)),
        )
        with pytest.raises(RuntimeError, match="wrong_principal"):
            resolve()
    assert not updates


def test_registry_query_rejects_missing_trust_pin_before_transport() -> None:
    with pytest.raises(ValueError, match="exactly match"):
        query_registry_for_matches_multi(
            ["http://registry"],
            signer=Ed25519Signer(b"\x0c" * 32),
            registry_authorities={},
        )
