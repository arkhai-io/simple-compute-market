"""JSON-lines bridge from the protected driver to marketplace-owned VM ports."""

from __future__ import annotations

import importlib
import json
import os
import sys
import traceback

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
    funding_profile: str
    accepted_negotiation_id: str
    obligation_id: str
    condition_hash: str
    fulfillment_state: str = "pending"
    terminal: Any | None = None


class LifecycleBridge:
    """Drive public marketplace ports while keeping buyer action URLs in memory only."""

    def __init__(self, marketplace: Any) -> None:
        self._marketplace = marketplace
        self._deals: dict[str, _Deal] = {}

    def request(self, body: dict[str, Any]) -> dict[str, Any]:
        action = body.get("action")
        if action == "ensure_payer_profile_fixture":
            method = body.get("payment_method")
            return self._marketplace.ensure_payer_profile_fixture(
                str(body.get("funding_profile", "")),
                str(body.get("interaction", "")),
                payment_method=str(method) if method else None,
            )
        if action == "complete_payer_setup":
            return self._marketplace.complete_payer_setup()
        if action == "verify_payer_setup":
            amounts = body.get("amounts")
            return self._marketplace.verify_payer_setup(
                amounts=(
                    tuple(int(value) for value in amounts)
                    if isinstance(amounts, list | tuple)
                    else None
                ),
                descriptor_code=(
                    str(body["descriptor_code"])
                    if body.get("descriptor_code") is not None
                    else None
                ),
            )
        if action == "prepare_collection":
            return self._prepare(case="collection")
        if action == "prepare_refund":
            capability = getattr(self._marketplace, "eligible_pretransfer_refund_available", None)
            if capability is None or capability() is not True:
                return {"ok": True, "available": False}
            return self._prepare(case="refund")
        if action == "observe_pending_funding":
            deal = self._deal(body)
            observed = self._marketplace.observe_pending_funding(deal.settlement_ref)
            if observed.get("funding_state") not in {"awaiting_payment", "pending"}:
                raise RuntimeError("authoritative funding was not pending")
            return {
                "ok": True,
                "funding_state": observed["funding_state"],
                "funding_profile": deal.funding_profile,
                "fulfillment_started": observed.get("fulfillment_started") is True,
            }
        if action == "wait_authoritative_funding":
            deal = self._deal(body)
            wait_funded = getattr(self._marketplace, "wait_funded", None)
            if wait_funded is None or wait_funded(deal.settlement_ref) is not True:
                raise ExternalUnavailable("authoritative funding did not converge")
            return {
                "ok": True,
                "funding_state": "funded",
                "funding_profile": deal.funding_profile,
                "authoritative_retrieval": True,
                "accepted_identity_preserved": True,
                "fulfillment_started": False,
            }
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
        if action in {
            "induce_test_ach_return",
            "induce_test_post_collection_loss",
        }:
            capability = getattr(self._marketplace, action, None)
            if capability is None:
                return {"ok": True, "available": False}
            deal = self._deal(body)
            return capability(deal.settlement_ref)
        if action == "wait_authoritative_loss":
            capability = getattr(self._marketplace, "wait_authoritative_loss", None)
            if capability is None:
                return {"ok": True, "available": False}
            deal = self._deal(body)
            return capability(deal.settlement_ref)
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
        payer_action = (
            None
            if materialized.action is None
            else {
                "kind": materialized.action.kind,
                "expires_at_unix": materialized.action.expires_at_unix,
                "url": materialized.action.url,
            }
        )
        deal = _Deal(
            settlement_ref=materialized.settlement_ref,
            operation_ref=materialized.operation_ref,
            amount=materialized.amount,
            currency=materialized.currency,
            transfer_group=materialized.transfer_group,
            funding_profile=materialized.accepted_funding_profile,
            accepted_negotiation_id=materialized.accepted_negotiation_id,
            obligation_id=materialized.obligation_ref,
            condition_hash=materialized.accepted_condition_hash,
        )
        self._deals[deal.operation_ref] = deal
        return {
            "ok": True,
            "available": True,
            "discovered": True,
            "negotiated": True,
            "materialized": True,
            "accepted_mechanism": negotiation.accepted_mechanism,
            "accepted_funding_profile": deal.funding_profile,
            "destination_account_ref": materialized.destination_account_ref,
            "condition_profile": "portable",
            "parties_authoritative": True,
            "funding_authorization_bound": materialized.funding_authorization_bound,
            "funding_authorization_operation_scoped": True,
            "operation_ref": deal.operation_ref,
            "marketplace_operation_id": deal.operation_ref,
            "accepted_negotiation_id": deal.accepted_negotiation_id,
            "obligation_id": deal.obligation_id,
            "accepted_condition_hash": deal.condition_hash,
            "payer_action": payer_action,
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
            "effect_operation_ref": deal.operation_ref,
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


def _refusal_class() -> type[BaseException]:
    """The marketplace's own refusal type, resolved the way the bridge resolves
    everything else it borrows: from the module it was pointed at, not from an
    import this package could not satisfy on its own.

    A build whose marketplace half predates the type still runs; it simply has
    nothing that raises it, and the except clause matches nothing.
    """

    module_name = os.environ.get(
        "HOSTED_SETTLEMENT_E2E_NETWORK_MODULE",
        "tests.e2e.roles.scenarios.vms.hosted.network",
    )
    try:
        return getattr(importlib.import_module(module_name), "HostedAuthorityRefusal")
    except (ImportError, AttributeError):
        class _Unraisable(BaseException):
            pass

        return _Unraisable


def _caused_by_timeout(exc: BaseException) -> bool:
    """Whether a failure is a deadline, however far it has been re-wrapped.

    A signed transport that gives up re-raises the deadline as its own error, so
    the class on top says the request failed while the cause says the storefront
    never answered. Those are different findings, and only one of them is the
    marketplace rejecting anything: nothing replied, so there was no contract to
    reject.
    """

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, TimeoutError):
            return True
        current = current.__cause__ or current.__context__
    return False


def main() -> int:
    # Stdout is the protocol and carries codes only. The reason behind a code
    # goes to stderr, which the driver reads for a development run and does
    # not read at all for a protected one -- so writing it here is safe in
    # both, and withholding it is what leaves a failed stage unexplainable.
    try:
        bridge = LifecycleBridge(_load_marketplace())
    except Exception:
        traceback.print_exc()
        return 2
    for line in sys.stdin:
        try:
            body = json.loads(line)
            if not isinstance(body, dict):
                raise RuntimeError("request must be an object")
            response = bridge.request(body)
        except _refusal_class() as refusal:
            traceback.print_exc()
            response = {
                "ok": False,
                "code": "authority_refused",
                "refusal": getattr(refusal, "code", "unknown"),
            }
        except TimeoutError:
            traceback.print_exc()
            response = {"ok": False, "code": "convergence_timeout"}
        except (ExternalUnavailable, OSError, ConnectionError):
            traceback.print_exc()
            response = {"ok": False, "code": "marketplace_unavailable"}
        except Exception as exc:
            traceback.print_exc()
            response = {
                "ok": False,
                "code": (
                    "convergence_timeout"
                    if _caused_by_timeout(exc)
                    else "marketplace_lifecycle_contract"
                ),
            }
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        sys.stdout.flush()
        if response.get("shutdown") is True:
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
