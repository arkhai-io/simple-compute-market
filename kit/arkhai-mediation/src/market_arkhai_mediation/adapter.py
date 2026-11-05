"""Lifecycle dispute adapter; only the named authority decides and applies remedies."""

import base64
from collections.abc import Callable, Sequence
import hashlib
import json
import time

from jsonschema.exceptions import ValidationError as SchemaValidationError
from market_deal_lifecycle.adapters import DeliveryEndIntent, DisputeBinding, InterfaceRequest
from market_deal_lifecycle.respondent import RespondentCase, RespondentPage
from market_deal_lifecycle.operations import OperationKeys
from market_deal_lifecycle.terms import DisputeAuthority
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, CaseRecord, DeliveryEndEffect, DisputeEvent, EvidenceItem,
    Effect as LifecycleEffect, FilingAnswer as LifecycleFilingAnswer, LifecycleCommand, LifecycleOutcome,
    PartEffect, PartHold, Pending, Rejected, Unknown,
)
from market_identity import Identity, Signer, canonical_json
from pydantic import JsonValue, ValidationError

from .client import (
    MediationAPIError, MediationClient, MediationError, MediationProtocolError,
    MediationTransportError,
)
from .claims import sign_claim, verify_claim
from .contract import INTERFACE, validate, wire
from .models import (
    Append, DeliveryEndClaim, Effect, Filing, ReadAfter, RespondentAfter, SignedDeliveryEndClaim, SignedRecordEntry,
)
from .records import RecordVerificationError


class MediationAdapter:
    supported_commands = frozenset({"dispute", "delivery_end", "append"})
    supported_intents = frozenset({"delivery_end"})

    def __init__(
        self, binding: DisputeBinding, agreement: dict, client: MediationClient | None = None, *,
        clock: Callable[[], int] = lambda: int(time.time()),
        concurrence: SignedDeliveryEndClaim | None = None,
    ):
        if client is not None and client.authority != binding.authority:
            raise ValueError("client does not address the Agreement's authority")
        selected = agreement.get("settlement", {})
        authorities = [
            section["adjudication"]["dispute"]
            for section in (selected.get("lifecycle") or {},)
            if "adjudication" in section
        ]
        if len(authorities) != 1 or DisputeAuthority.model_validate(authorities[0]) != binding.authority:
            raise ValueError("binding differs from the exact Agreement's authority")
        validate("Sha256Hex", binding.commitment_ref)
        self.binding = binding
        self._agreement = json.loads(canonical_json(agreement))
        self.agreement_digest = hashlib.sha256(canonical_json(agreement)).hexdigest()
        self._client = client
        self.clock = clock
        self._concurrence = concurrence.model_copy(deep=True) if concurrence is not None else None

    @property
    def client(self) -> MediationClient:
        if self._client is None:
            raise MediationError("Agreement mediation client is unavailable; receipt claims remain local")
        return self._client

    def sign_delivery_end(self, intent: DeliveryEndIntent, signer: Signer) -> dict[str, JsonValue]:
        if signer.identity != Identity.model_validate(self._agreement["seller"]):
            raise ValueError("delivery claim signer is not the Agreement seller")
        return wire(sign_claim(
            agreement=self.agreement_digest, signer=signer,
            claim=DeliveryEndClaim.model_validate(intent.model_dump(mode="json")),
        ))

    def verify_delivery_end(self, signed: dict[str, JsonValue], intent: DeliveryEndIntent) -> bool:
        try:
            return verify_claim(
                SignedDeliveryEndClaim.model_validate(signed), agreement=self.agreement_digest,
                seller=Identity.model_validate(self._agreement["seller"]),
                claim=DeliveryEndClaim.model_validate(intent.model_dump(mode="json")),
            )
        except (ValueError, ValidationError):
            return False

    def concurrent_request(
        self, intent: DeliveryEndIntent, signed: dict[str, JsonValue] | None,
    ) -> InterfaceRequest | Rejected:
        if signed is not None and not self.verify_delivery_end(signed, intent):
            return Rejected(reason="concurrence does not bind the Agreement seller and exact claim")
        return self.delivery_end_request(
            intent, concurrence=SignedDeliveryEndClaim.model_validate(signed) if signed is not None else None,
        )

    def build_request(self, intent: DeliveryEndIntent) -> InterfaceRequest | Rejected:
        return self.delivery_end_request(intent, concurrence=self._concurrence)

    def delivery_end_request(
        self, intent: DeliveryEndIntent, *, concurrence: SignedDeliveryEndClaim | None = None,
        claim: str = "End delivery under the Agreement.", items: Sequence[dict] = (),
    ) -> InterfaceRequest | Rejected:
        """Attach a verified receipt claim without selecting or computing remedies."""
        value = intent.model_dump(mode="json")
        payload: dict[str, JsonValue] = {"request": value, "claim": claim, "items": list(items)}
        if concurrence is not None:
            if not verify_claim(
                concurrence, agreement=self.agreement_digest,
                seller=Identity.model_validate(self._agreement["seller"]),
                claim=DeliveryEndClaim.model_validate(value),
            ):
                return Rejected(reason="concurrence does not bind the Agreement seller and exact claim")
            payload["concurrence"] = wire(concurrence)
        request = InterfaceRequest(interface=INTERFACE, payload=payload)
        return self.validate_request(request) or request

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

    def build_append(self, case_ref: str, items: list[EvidenceItem]) -> dict[str, JsonValue] | Rejected:
        """Package exact bodies with their proof headers and verification context.

        The outer evidence is a seller-produced export, not a new signature on
        the inner bytes. Its original body and authentication context remain
        available together for the authority to verify independently.
        """
        producer = Identity.model_validate(self._agreement["seller"])
        value = {"case_ref": case_ref, "items": [
            {
                "kind": "arkhai.market-evidence.v1",
                "producer": f"{producer.scheme.value}:{producer.identifier}",
                "at": item.recorded_at,
                "sha256": hashlib.sha256(canonical_json(item)).hexdigest(),
                "bytes": base64.urlsafe_b64encode(canonical_json(item)).decode().rstrip("="),
            } for item in items
        ]}
        try:
            return validate("Append", value)
        except (ValueError, ValidationError, SchemaValidationError):
            return Rejected(reason="case append requires valid evidence")

    async def respondent(self, after: str = "", limit: int = 100) -> RespondentPage:
        page = await self.client.respondent(RespondentAfter(after=after, limit=limit))
        cases = []
        for pending in page.cases:
            value = wire(pending)
            # Listing is discovery, not signed evidence. Bind it to the filed
            # entry from that Agreement before a seller signs any concurrence.
            cursor = 0
            filed = None
            while True:
                records = await self.client.read_record(ReadAfter.model_validate({
                    "agreement": value["agreement"], "after": cursor, "limit": 1000,
                }), transaction=value["transaction"])
                filed = next((wire(entry)["entry"] for entry in records.entries
                              if wire(entry)["entry"]["record_ref"] == value["filed_record_ref"]), None)
                if filed is not None or not records.has_more:
                    break
                cursor = records.next_after
            if (filed is None or filed["kind"] != "filed" or filed["case_ref"] != value["case_ref"]
                    or filed["filing"]["request"] != value["request"] or filed["at"] != value["filed_at"]):
                raise MediationProtocolError("respondent case differs from its signed filed record")
            intent = (DeliveryEndIntent.model_validate(value["request"])
                      if value["request"]["kind"] == "delivery_end" else None)
            cases.append(RespondentCase(
                case_ref=value["case_ref"], agreement_ref=value["agreement"],
                commitment_ref=value["transaction"], filed_at=value["filed_at"],
                filed_record_ref=value["filed_record_ref"], intent=intent,
            ))
        return RespondentPage(cases=cases, next_after=page.next_after, has_more=page.has_more)

    def build_answer(
        self, case: RespondentCase, *, matching: bool, items: list[EvidenceItem], signer: Signer,
    ) -> dict[str, JsonValue] | Rejected:
        if (case.agreement_ref != self.agreement_digest or case.commitment_ref != self.binding.commitment_ref
                or signer.identity != Identity.model_validate(self._agreement["seller"])):
            return Rejected(reason="respondent answer differs from the exact Agreement or seller")
        if not matching or case.intent is None:
            return self.build_append(case.case_ref, items)
        signed = self.sign_delivery_end(case.intent, signer)
        return validate("Append", {"case_ref": case.case_ref, "concurrence": signed})

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
        if value["request"]["kind"] == "delivery_end":
            if value["request"]["ended_at"] > self.clock():
                raise ValueError("delivery end cannot be in the future")
        for effect in value["request"].get("effects", []):
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
            filing_key = keys.filing()
            if wire(filing)["request"]["kind"] == "delivery_end":
                identity = hashlib.sha256(canonical_json({
                    "commitment": self.binding.commitment_ref, "agreement": self.agreement_digest,
                    "authority": self.binding.authority.model_dump(mode="json"),
                })).hexdigest()
                view = await self._read(unregistered_for_filing=True)
                if not isinstance(view.outcome, Accepted):
                    return view.outcome
                originals = [event for event in view.disputes if event.kind == "filed" and
                             json.loads(event.items[0].body)["entry"]["filing"]["request"]["kind"] == "delivery_end"]
                if originals:
                    fixed = wire(filing)["request"]
                    if len(originals) != 1 or json.loads(originals[0].items[0].body)["entry"]["filing"]["request"] != fixed:
                        return Rejected(reason="repair required: delivery-end revision requires resolved prior rulings and effects")
                    answer = wire(await self.client.case(
                        originals[0].case_ref, agreement=self.agreement_digest,
                        transaction=self.binding.commitment_ref,
                    ))
                    if answer["status"] != "accepted":
                        return _failure(answer)
                    return await self._filing_answer(answer["case"])
                # Only the original caller may write while its result is uncertain.
                # Other callers adopt a signed equivalent above, or fail closed.
                owner = hashlib.sha256(canonical_json({
                    "operation_key": command.operation_key, "filing": wire(filing),
                })).hexdigest()
                if keys.store is None or not await keys.store.check_and_record(
                    command.negotiation_id, "mediation-delivery-end:" + identity, owner,
                ):
                    return Pending(reason="original delivery-end filing must resolve before adoption or revision")
                filing_key = hashlib.sha256(canonical_json([identity, wire(filing)["request"]])).hexdigest()
            sent = True
            answer = wire(await self.client.file(filing, idempotency_key=filing_key))
            if answer["status"] != "accepted":
                return _failure(answer)
            return await self._filing_answer(answer["case"])
        except (ValueError, ValidationError, SchemaValidationError) as exc:
            if sent:
                return Unknown(reason="mediation write response failed verification; read before acting")
            return Rejected(reason=f"invalid mediation command: {type(exc).__name__}")
        except MediationError as exc:
            return _boundary_failure(exc)

    async def _filing_answer(self, case: dict) -> LifecycleOutcome:
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

    async def read(self) -> AuthorityView:
        return await self._read()

    async def _read(self, *, unregistered_for_filing: bool = False) -> AuthorityView:
        after = 0
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
            # The authority learns the Agreement from its first filing. A missing
            # initial record may permit that write, not prove an empty history
            # to watches or acknowledge a case without its signed filed entry.
            if (unregistered_for_filing and after == 0 and not events
                    and isinstance(exc, MediationAPIError)
                    and exc.status == 404 and exc.code == "invalid_request"):
                return AuthorityView(outcome=Accepted())
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
