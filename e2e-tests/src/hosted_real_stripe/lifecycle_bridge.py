"""JSON-lines bridge from the protected driver to marketplace-owned VM ports."""

from __future__ import annotations

import importlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MECHANISM = "fiat.stripe.v1"


class ExternalUnavailable(RuntimeError):
    """The ordinary marketplace or authority could not be observed."""


@dataclass
class _Deal:
    settlement_ref: str
    operation_ref: str
    amount: int
    currency: str
    transfer_group: str
    fulfillment_state: str = "pending"
    terminal: Any | None = None


class LifecycleBridge:
    """Drive public marketplace ports while keeping buyer action URLs in memory only."""

    def __init__(self, marketplace: Any) -> None:
        self._marketplace = marketplace
        self._deals: dict[str, _Deal] = {}

    def request(self, body: dict[str, Any]) -> dict[str, Any]:
        action = body.get("action")
        if action == "prepare_collection":
            return self._prepare(case="collection")
        if action == "prepare_refund":
            capability = getattr(self._marketplace, "eligible_pretransfer_refund_available", None)
            if capability is None or capability() is not True:
                return {"ok": True, "available": False}
            return self._prepare(case="refund")
        if action == "wait_authoritative_funding":
            deal = self._deal(body)
            wait_funded = getattr(self._marketplace, "wait_funded", None)
            if wait_funded is None or wait_funded(deal.settlement_ref) is not True:
                raise ExternalUnavailable("authoritative funding did not converge")
            return {"ok": True}
        if action == "complete_portable_vm_fulfillment":
            deal = self._deal(body)
            snapshot = self._marketplace.complete_vm_fulfillment(deal.settlement_ref)
            if snapshot.condition_decision != "satisfied":
                raise RuntimeError("portable collection condition was not satisfied")
            deal.fulfillment_state = "fulfilled"
            return {"ok": True}
        if action == "wait_authoritative_collection":
            deal = self._deal(body)
            terminal = self._marketplace.wait_terminal(deal.settlement_ref)
            self._require_terminal(terminal, deal, kind="transfer", state="collected")
            deal.terminal = terminal
            return self._terminal_response(deal)
        if action == "request_eligible_pretransfer_refund":
            deal = self._deal(body)
            reclaim = getattr(self._marketplace, "request_eligible_pretransfer_refund", None)
            terminal = (
                reclaim(deal.settlement_ref)
                if reclaim is not None
                else self._marketplace.reclaim(deal.settlement_ref)
            )
            self._require_terminal(terminal, deal, kind="refund", state="reclaimed")
            deal.terminal = terminal
            deal.fulfillment_state = "completed"
            return {"ok": True}
        if action == "wait_authoritative_refund":
            deal = self._deal(body)
            if deal.terminal is None:
                raise RuntimeError("eligible pre-transfer refund was not requested")
            return self._terminal_response(deal, authority_state="refunded")
        if action == "recover_eligible_pretransfer_refund":
            deal = self._deal(body)
            recover = getattr(self._marketplace, "recover_eligible_pretransfer_refund", None)
            terminal = (
                recover(deal.settlement_ref)
                if recover is not None
                else self._marketplace.reclaim(deal.settlement_ref)
            )
            self._require_terminal(terminal, deal, kind="refund", state="reclaimed")
            return self._terminal_response(deal, authority_state="refunded")
        if action == "shutdown":
            return {"ok": True, "shutdown": True}
        raise RuntimeError("unsupported marketplace lifecycle action")

    def _prepare(self, *, case: str) -> dict[str, Any]:
        select_case = getattr(self._marketplace, "select_stripe_test_case", None)
        if select_case is not None:
            select_case(case)
        composition = self._marketplace.verify_composition()
        if composition.authority_ready is not True:
            raise ExternalUnavailable("ordinary hosted authority is not ready")
        runtime = self._marketplace.verify_runtime()
        if not (runtime.wallet_free and runtime.runtime_ready and runtime.account_ready):
            raise ExternalUnavailable("wallet-free hosted runtime/account is not ready")
        listing = self._marketplace.create_and_publish_listing()
        discovered = self._marketplace.discover_listing(listing.listing_id)
        if discovered != listing.listing_id:
            raise RuntimeError("registry discovery returned the wrong listing")
        negotiation = self._marketplace.negotiate(discovered)
        if negotiation.accepted_mechanism != MECHANISM:
            raise RuntimeError("negotiation did not pin the hosted mechanism")
        materialized = self._marketplace.materialize(negotiation.negotiation_id)
        if materialized.action.kind != "redirect":
            raise RuntimeError("materialization did not return a Checkout redirect")
        if case == "refund":
            keep_unresolved = getattr(
                self._marketplace,
                "keep_fulfillment_unresolved_for_refund",
                None,
            )
            if keep_unresolved is None:
                raise RuntimeError("refund scenario has no deterministic unfulfilled control")
            keep_unresolved()
        deal = _Deal(
            settlement_ref=materialized.settlement_ref,
            operation_ref=materialized.operation_ref,
            amount=materialized.amount,
            currency=materialized.currency,
            transfer_group=materialized.transfer_group,
        )
        self._deals[deal.operation_ref] = deal
        return {
            "ok": True,
            "available": True,
            "discovered": True,
            "negotiated": True,
            "materialized": True,
            "accepted_mechanism": negotiation.accepted_mechanism,
            "condition_profile": "portable",
            "operation_ref": deal.operation_ref,
            "checkout_url": materialized.action.url,
            "amount": deal.amount,
            "currency": deal.currency,
            "transfer_group": deal.transfer_group,
            "reclaim_eligible_at_unix": materialized.expiration_unix,
        }

    def _deal(self, body: dict[str, Any]) -> _Deal:
        operation_ref = body.get("operation_ref")
        if not isinstance(operation_ref, str) or operation_ref not in self._deals:
            raise RuntimeError("unknown marketplace operation")
        return self._deals[operation_ref]

    @staticmethod
    def _require_terminal(terminal: Any, deal: _Deal, *, kind: str, state: str) -> None:
        if (
            terminal.operation_ref != deal.operation_ref
            or terminal.effect_kind != kind
            or terminal.marketplace_status != state
            or terminal.authority_status != state
        ):
            raise RuntimeError("marketplace and authority terminal state did not converge")

    @staticmethod
    def _terminal_response(deal: _Deal, *, authority_state: str | None = None) -> dict[str, Any]:
        terminal = deal.terminal
        assert terminal is not None
        return {
            "ok": True,
            "marketplace_state": terminal.marketplace_status,
            "authority_state": authority_state or terminal.authority_status,
            "fulfillment_state": deal.fulfillment_state,
        }


def _load_marketplace() -> Any:
    target = os.environ.get("HOSTED_SETTLEMENT_E2E_MARKETPLACE_FACTORY", "").strip()
    buyer_config = os.environ.get("HOSTED_SETTLEMENT_E2E_BUYER_CONFIG", "").strip()
    if not target or ":" not in target or not buyer_config:
        raise RuntimeError("marketplace lifecycle factory/config is unavailable")
    module_name, attribute = target.split(":", 1)
    factory = getattr(importlib.import_module(module_name), attribute)
    return factory(buyer_config=Path(buyer_config))


def main() -> int:
    try:
        bridge = LifecycleBridge(_load_marketplace())
    except Exception:
        return 2
    for line in sys.stdin:
        try:
            body = json.loads(line)
            if not isinstance(body, dict):
                raise RuntimeError("request must be an object")
            response = bridge.request(body)
        except TimeoutError:
            response = {"ok": False, "code": "convergence_timeout"}
        except (ExternalUnavailable, OSError, ConnectionError):
            response = {"ok": False, "code": "marketplace_unavailable"}
        except Exception:
            response = {"ok": False, "code": "marketplace_lifecycle_contract"}
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        sys.stdout.flush()
        if response.get("shutdown") is True:
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
