"""Lifecycle dispute adapter; only the named authority decides and applies remedies."""

import base64
from collections.abc import Callable, Sequence
import hashlib
import json
import time

from jsonschema.exceptions import ValidationError as SchemaValidationError
from market_deal_lifecycle.adapters import DeliveryEndIntent, DisputeBinding, InterfaceRequest
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, CaseRecord, DeliveryEndEffect, DisputeEvent, EvidenceItem,
    Effect as LifecycleEffect, FilingAnswer as LifecycleFilingAnswer, LifecycleCommand, LifecycleOutcome,
    PartEffect, PartHold, Pending, Rejected, Unknown,
)
from market_identity import canonical_json
from pydantic import ValidationError

from .client import (
    MediationAPIError, MediationClient, MediationError, MediationProtocolError,
    MediationTransportError,
)
from .contract import INTERFACE, validate, wire
from .models import Append, Effect, Filing, ReadAfter, SignedRecordEntry
from .records import RecordVerificationError


class MediationAdapter:
    supported_commands = frozenset({"dispute", "append"})
    supported_intents: frozenset[str] = frozenset()

    def __init__(
        self, binding: DisputeBinding, agreement: dict, client: MediationClient, *,
        clock: Callable[[], int] = lambda: int(time.time()),
    ):
        if client.authority != binding.authority:
            raise ValueError("client does not address the Agreement's authority")
        selected = agreement.get("settlement", {})
        authorities = [
            section["adjudication"]["dispute"]
            for section in (selected.get("lifecycle", {}), selected.get("params", {}))
            if "adjudication" in section
        ]
        if len(authorities) != 1 or DisputeAuthority.model_validate(authorities[0]) != binding.authority:
            raise ValueError("binding differs from the exact Agreement's authority")
        validate("Sha256Hex", binding.commitment_ref)
        self.binding = binding
        self._agreement = json.loads(canonical_json(agreement))
        self.agreement_digest = hashlib.sha256(canonical_json(agreement)).hexdigest()
        self.client = client
        self.clock = clock

    def build_request(self, intent: DeliveryEndIntent) -> Rejected:
        return Rejected(reason="delivery_end lifecycle mapping is not enabled")

    def effects_request(
        self, effects: Sequence[Effect | dict], *, claim: str, items: Sequence[dict] = (),
    ) -> InterfaceRequest:
        """Construct a free-form request, not a locally computed monetary remedy."""
        request = InterfaceRequest(
            interface=INTERFACE,
            payload={
                "request": {"kind": "effects", "effects": [
                    wire(effect) if isinstance(effect, Effect) else effect for effect in effects
                ]},
                "claim": claim, "items": list(items),
            },
        )
        refusal = self.validate_request(request)
        if refusal is not None:
            raise ValueError(refusal.reason)
        return request

    def validate_request(self, request: InterfaceRequest) -> Rejected | None:
        try:
            self._filing(request)
        except (ValueError, ValidationError, SchemaValidationError) as exc:
            return Rejected(reason=f"invalid mediation request: {type(exc).__name__}")
        return None

    def _filing(self, request: InterfaceRequest) -> Filing:
        if request.interface != INTERFACE:
            raise ValueError("request names another interface")
        value = {
            **request.payload, "transaction": self.binding.commitment_ref,
            "agreement": self._agreement,
        }
        validate("Filing", value)
        # Free-form filings name requested effects; delivery-end intents need their mapper.
        if value["request"]["kind"] != "effects":
            raise ValueError("this adapter only enables free-form effects requests")
        for effect in value["request"]["effects"]:
            if effect["kind"] == "award":
                raise ValueError("bond awards are reserved")
            if effect["kind"] == "end_delivery" and effect["at"] > self.clock():
                raise ValueError("delivery end cannot be in the future")
        _check_items(value["items"])
        return Filing.model_validate(value)

    async def submit(
        self, command: LifecycleCommand, request: InterfaceRequest | None, keys: OperationKeys,
    ) -> LifecycleOutcome:
        if (
            command.negotiation_id != self.binding.negotiation_id
            or keys.negotiation_id != command.negotiation_id
            or keys.operation_key != command.operation_key
            or command.kind not in self.supported_commands
        ):
            return Rejected(reason="unsupported command or mismatched mediation binding")
        sent = False
        try:
            if command.kind == "append":
                append_value = validate("Append", dict(command.payload))
                _check_items(append_value.get("items", []))
                append = Append.model_validate(append_value)
                sent = True
                append_answer = await self.client.append(
                    append, idempotency_key=keys.append(str(append_value["case_ref"])),
                    agreement=self.agreement_digest, transaction=self.binding.commitment_ref,
                )
                raw = wire(append_answer)
                if raw["status"] == "accepted":
                    return Accepted(records=[self._event(SignedRecordEntry.model_validate(raw["record"]))])
                return _failure(raw)
            if request is None:
                return Rejected(reason="mediation filing request is missing")
            filing = self._filing(request)
            sent = True
            answer = wire(await self.client.file(filing, idempotency_key=keys.filing()))
            if answer["status"] != "accepted":
                return _failure(answer)
            case = answer["case"]
            if case["agreement"] != self.agreement_digest or case["transaction"] != self.binding.commitment_ref:
                raise MediationProtocolError("filing answer names another deal")
            # A filing answer has no signed record reference. Obtain it from the
            # authority record before returning a usable lifecycle acknowledgement.
            view = await self.read()
            if not isinstance(view.outcome, Accepted):
                return Pending(reason=f"case {case['case_ref']} accepted; signed record unavailable")
            filed = next((
                event for event in view.disputes
                if event.case_ref == case["case_ref"] and event.kind == "filed"
            ), None)
            if filed is None:
                return Pending(reason=f"case {case['case_ref']} accepted; filed record pending")
            return Accepted(
                filing=LifecycleFilingAnswer(
                    case_ref=case["case_ref"], record_ref=filed.record_ref,
                    parts=[PartHold(
                        part=str(part["part"]), status=part["status"],
                        reason=part.get("reason", "extension accepted"),
                        extension_ref=str(part["extension_ref"]) if part["status"] == "held" else None,
                    ) for part in case["parts"]],
                ),
                records=[filed],
            )
        except (ValueError, ValidationError, SchemaValidationError) as exc:
            if sent:
                return Unknown(reason="mediation write response failed verification; read before acting")
            return Rejected(reason=f"invalid mediation command: {type(exc).__name__}")
        except MediationError as exc:
            return _boundary_failure(exc)

    async def read(self) -> AuthorityView:
        try:
            after = 0
            events = []
            cases: dict[str, CaseRecord] = {}
            while True:
                page = await self.client.read_record(ReadAfter.model_validate({
                    "agreement": self.agreement_digest, "after": after, "limit": 1000,
                }), transaction=self.binding.commitment_ref)
                for signed in page.entries:
                    entry = wire(signed)["entry"]
                    case = entry["case_ref"]
                    if (entry["kind"] == "filed") == (case in cases):
                        raise MediationProtocolError("record case association is not contiguous")
                    event = self._event(signed)
                    events.append(event)
                    cases[case] = CaseRecord(
                        case_ref=case, state=event.kind, record_ref=event.record_ref, outcome=event.outcome,
                    )
                after = page.next_after
                if not page.has_more:
                    break
            # Hold extensions belong to the payments record. Case protection is
            # not a claim that a finite extension is still open.
            return AuthorityView(outcome=Accepted(), disputes=events, cases=list(cases.values()))
        except (RecordVerificationError, SchemaValidationError, ValidationError, MediationError, ValueError) as exc:
            if isinstance(exc, MediationError):
                outcome = _boundary_failure(exc)
            else:
                outcome = Rejected(reason="mediation record verification failed")
            return AuthorityView(outcome=outcome)

    def _event(self, signed: SignedRecordEntry) -> DisputeEvent:
        raw = wire(signed)
        entry = raw["entry"]
        effects: list[LifecycleEffect] = []
        for item in entry.get("outcome", []):
            effect = item["effect"]
            common = {"effect_id": item["id"], "applied": item["state"] == "applied"}
            if effect["kind"] == "end_delivery":
                effects.append(DeliveryEndEffect(**common, kind="delivery_end", at=effect["at"]))
            elif effect["kind"] in {"reverse", "award", "stop"}:
                effects.append(PartEffect.model_validate({
                    **common, "kind": effect["kind"], "part": str(effect["part"]),
                    "amount": effect.get("amount"), "at": effect.get("at"),
                    "settles_through": {
                        "charged": "started_period", "returned": "last_boundary", "prorated": "stop",
                    }.get(effect.get("partialPeriod")),
                }))
            # Aggregate penalties have no part. Preserve the signed authority
            # answer below, never invent a per-part monetary decomposition.
        evidence = EvidenceItem(
            evidence_id=entry["record_ref"], kind="arkhai.mediation.signed-record.v1",
            classification="independent", recorded_at=entry["at"],
            body=base64.b64encode(canonical_json(raw)),
        )
        return DisputeEvent(
            negotiation_id=self.binding.negotiation_id, commitment_ref=self.binding.commitment_ref,
            case_ref=entry["case_ref"], kind=entry["kind"], actor=entry["actor"], at=entry["at"],
            sequence=entry["sequence"], record_ref=entry["record_ref"],
            items=[evidence], outcome=effects,
        )


def _check_items(items: list) -> None:
    for item in items:
        encoded = item["bytes"]
        body = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        if hashlib.sha256(body).hexdigest() != item["sha256"]:
            raise ValueError("evidence digest does not match original bytes")


def _failure(answer: dict) -> LifecycleOutcome:
    if answer["status"] == "rejected":
        return Rejected(reason=answer["reason"] + ": " + answer["message"])
    if answer["status"] == "pending":
        return Pending(reason="mediation protection pending for " + answer["case_ref"])
    if answer.get("code") in {"protection_incomplete", "temporarily_unavailable"}:
        return Pending(reason="mediation error: " + answer["code"])
    return Rejected(reason="mediation error: " + answer.get("code", "invalid_response"))


def _boundary_failure(exc: MediationError) -> LifecycleOutcome:
    if isinstance(exc, MediationTransportError):
        return Unknown(reason="mediation transport result is unknown; read or retry the same key")
    if isinstance(exc, MediationProtocolError):
        return Unknown(reason="mediation response violates its contract; repair and read before acting")
    if isinstance(exc, MediationAPIError) and exc.status >= 500:
        return Pending(reason="mediation service unavailable; read or retry the same key")
    return Rejected(reason=str(exc))
