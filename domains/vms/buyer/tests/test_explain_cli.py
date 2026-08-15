from __future__ import annotations

import json
from types import SimpleNamespace

from core_buyer import (
    BuyerSettlementExplanation,
    RegistryDiscovery,
    RegistryQueryPlan,
)
from domains.vms.buyer import listing_cli
from domains.vms.buyer.cli import app
from typer.testing import CliRunner

runner = CliRunner()


def test_listing_explain_emits_stable_json_and_stops_before_normal_selection(
    monkeypatch,
) -> None:
    listing = {"listing_id": "L1", "settlement_options": []}
    discovery = RegistryDiscovery(
        listings=(listing,),
        query_plans=(
            RegistryQueryPlan(
                registry_url="http://registry",
                etag="vm-v1",
                filter_spec_version=1,
                schema_id="compute.v1",
                schema_version=1,
                canonical_query="gpu_model=H200",
                parameters=(("gpu_model", "H200"),),
            ),
        ),
    )
    calls: list[str] = []

    class Policy:
        def compile_clauses(self, clauses):
            assert tuple(clauses) == ()
            return ()

        def explain_listings(self, listings, **kwargs):
            calls.append("explain")
            assert list(listings) == [listing]
            return BuyerSettlementExplanation(
                resource_listing_count=1,
                advertised_option_count=0,
                compatible_listing_count=0,
                compatible_option_count=0,
                clauses=(),
                winning_clause_index=None,
                policy_mechanism=None,
                policy_listing_count=0,
                selected_option_id=None,
                rejection_categories={"no_settlement_options": 1},
            )

        def select_listings(self, *_args, **_kwargs):
            raise AssertionError("explain continued into normal selection")

    monkeypatch.setattr(
        listing_cli,
        "_registry_context",
        lambda **_kwargs: (
            SimpleNamespace(),
            SimpleNamespace(),
            ["http://registry"],
            {"http://registry": SimpleNamespace()},
            {},
            5.0,
        ),
    )
    monkeypatch.setattr(
        listing_cli,
        "explain_registry_query",
        lambda *_args, **_kwargs: discovery,
    )
    monkeypatch.setattr(
        listing_cli,
        "query_registry_for_matches_multi",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("explain used the normal discovery path")
        ),
    )
    monkeypatch.setattr(
        listing_cli,
        "resolve_buyer_settlement_policy",
        lambda **_kwargs: Policy(),
    )

    result = runner.invoke(
        app,
        ["listing", "list", "--resource", "gpu_model=H200", "--explain"],
    )

    assert result.exit_code == 0, result.output
    assert calls == ["explain"]
    payload = json.loads(result.output.split("Explanation JSON:\n", 1)[1])
    assert payload["resource"]["canonical_ast"] == [
        {"field": "gpu_model", "operator": "=", "value": "H200"}
    ]
    assert payload["settlement"]["rejection_categories"] == {"no_settlement_options": 1}
    assert payload["mutation_boundary"]["stopped_before"][-1] == "run_persistence"


def test_listing_rejects_clause_with_generated_fields_before_registry(
    monkeypatch,
) -> None:
    from domains.vms.buyer.settlement_composition import (
        resolve_buyer_settlement_policy,
    )

    policy = resolve_buyer_settlement_policy(
        {
            "Settlement": {
                "schema_version": 1,
                "priority": ["fiat.stripe.v1"],
                "stripe": {"enabled": True},
            }
        }
    )
    monkeypatch.setattr(
        listing_cli,
        "resolve_buyer_settlement_policy",
        lambda **_kwargs: policy,
    )
    monkeypatch.setattr(
        listing_cli,
        "_registry_context",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid clause reached registry discovery")
        ),
    )

    result = runner.invoke(
        app,
        ["listing", "list", "--settlement", "mechanism=ghost"],
    )

    assert result.exit_code == 2
    assert "Accepted settlement fields:" in result.output
    assert "asset" in result.output
    assert "alkahest.chain" in result.output
    assert "stripe.funding_profile" in result.output
