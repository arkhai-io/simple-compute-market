"""Vector-derived in-process contract peer, not a payment or mediation rules engine.

Protection and outcomes are injected authority answers. No financial remedy is
computed here; HTTP doubles can reuse these same installed vectors and signers.
"""

from copy import deepcopy
import hashlib
import json
from urllib.parse import unquote

import httpx
from market_identity import canonical_json

from ..contract import validate, vectors, wire
from . import sign_record


class MediationContractFake:
    def __init__(self):
        self.data = vectors()
        self.authority = deepcopy(self.data["description"]["dispute"])
        self.payer = "11111111-1111-4111-8111-111111111111"
        self.payee = "22222222-2222-4222-8222-222222222222"
        # Public deterministic development credentials; never use on a public network.
        self.tokens = {"fixture-payer": self.payer, "fixture-payee": self.payee}
        self.parts = deepcopy(self.data["filing"]["answer"]["case"]["parts"])
        self.entries: list[dict] = []
        self.cases: dict[str, dict] = {}
        self.replays: dict[tuple, tuple[bytes, dict]] = {}
        self.requests: list[httpx.Request] = []
        self.next_filing_answer: dict | None = None
        self.lose_next_response = False
        self.close_after_append = False
        self._extension = 0
        self._clock = self.data["records"][0]["signed"]["entry"]["at"]

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        actor = self.tokens.get(request.headers.get("Authorization", "").removeprefix("Bearer "))
        if actor is None:
            return httpx.Response(401, json={"code": "authentication_required"})
        path = request.url.path
        if request.method == "POST":
            payload = json.loads(request.content)
            definition = {"/cases": "Filing", "/append": "Append"}.get(path)
            if definition is None:
                return httpx.Response(404)
            validate(definition, payload)
            key = (actor, request.headers["Idempotency-Key"], path)
            content = canonical_json(payload)
            prior = self.replays.get(key)
            if prior is not None:
                answer = prior[1] if prior[0] == content else {
                    "status": "error", "code": "idempotency_conflict", "message": "key changed content",
                }
            else:
                answer = self._file(actor, payload) if path == "/cases" else self._append(actor, payload)
                self.replays[key] = (content, deepcopy(answer))
            if self.lose_next_response:
                self.lose_next_response = False
                raise httpx.ReadError("injected loss after authority acknowledgement", request=request)
            return httpx.Response(200, json=answer)
        if path == "/respondent":
            after = int(request.url.params.get("after") or "0")
            limit = int(request.url.params.get("limit", "100"))
            pending = []
            for position, respondent_case in enumerate(self.cases.values(), 1):
                records = [entry["entry"] for entry in self.entries if entry["entry"]["case_ref"] == respondent_case["case_ref"]]
                filed = records[0]
                if (position <= after or respondent_case["state"] == "closed" or filed["actor"] == actor
                        or any(entry["kind"] == "appended" and entry["actor"] == actor for entry in records)):
                    continue
                pending.append((position, {
                    **{key: respondent_case[key] for key in ("case_ref", "transaction", "agreement", "parts")},
                    "filed_at": filed["at"], "filer": "payer" if filed["actor"] == self.payer else "payee",
                    "request": filed["filing"]["request"], "filed_record_ref": filed["record_ref"],
                }))
            selected_cases = pending[:limit]
            return httpx.Response(200, json={
                "cases": [value for _, value in selected_cases],
                "next_after": str(selected_cases[-1][0]) if selected_cases else str(after),
                "has_more": len(pending) > limit,
            })
        if path == "/record":
            agreement = request.url.params["agreement"]
            after = int(request.url.params["after"])
            limit = int(request.url.params.get("limit", "100"))
            entries = [
                entry for entry in self.entries
                if entry["entry"]["agreement"] == agreement and entry["entry"]["sequence"] > after
            ]
            selected = entries[:limit]
            return httpx.Response(200, json={
                "agreement": agreement, "entries": selected,
                "next_after": selected[-1]["entry"]["sequence"] if selected else after,
                "has_more": len(entries) > len(selected),
            })
        if path.startswith("/cases/"):
            case = self.cases.get(unquote(path[len("/cases/"):]))
            if case is not None:
                return httpx.Response(200, json={"status": "accepted", "case": case})
        return httpx.Response(404, json={"code": "invalid_request"})

    def _file(self, actor: str, filing: dict) -> dict:
        if self.next_filing_answer is not None:
            answer, self.next_filing_answer = self.next_filing_answer, None
            validate("FilingAnswer", answer)
            return answer
        case_ref = "case-fixture-" + str(len(self.cases) + 1)
        parts = deepcopy(self.parts)
        for part in parts:
            if part["status"] == "held":
                self._extension += 1
                part["extension_ref"] = self._extension
        case = {
            "case_ref": case_ref, "transaction": filing["transaction"],
            "agreement": hashlib.sha256(canonical_json(filing["agreement"])).hexdigest(),
            "state": "open", "parts": parts,
        }
        self.cases[case_ref] = case
        self._record(case_ref, actor, "filed", filing=filing)
        if all(part["status"] == "not_held" for part in parts):
            self._record(
                case_ref, self.authority["account"], "closed", reason="dismissed",
                dismissal_reason="nothing_held", outcome=[],
            )
            case["state"] = "closed"
        return {"status": "accepted", "case": deepcopy(case)}

    def _append(self, actor: str, payload: dict) -> dict:
        case = self.cases.get(payload["case_ref"])
        if case is None:
            return {"status": "rejected", "reason": "case_not_found", "message": "unknown case"}
        if case["state"] == "closed":
            return {"status": "rejected", "reason": "case_closed", "message": "case is closed"}
        if "concurrence" in payload and actor != self.payee:
            return {"status": "rejected", "reason": "actor_not_party", "message": "only payee concurs"}
        fields = {"items": payload.get("items", [])}
        if "concurrence" in payload:
            fields["concurrence"] = payload["concurrence"]
        signed = self._record(case["case_ref"], actor, "appended", **fields)
        if self.close_after_append:
            self.close_after_append = False
            self.decide(case["case_ref"], [])
        return {"status": "accepted", "record": signed}

    def decide(self, case_ref: str, outcome: list[dict]) -> None:
        """Inject an operator's answer, never calculate it from a claim."""
        self._record(
            case_ref, self.authority["account"], "ruled", basis="operator", outcome=outcome,
        )
        self._record(
            case_ref, self.authority["account"], "closed",
            reason="ruled", basis="operator", outcome=outcome,
        )
        self.cases[case_ref]["state"] = "closed"

    def _record(self, case_ref: str, actor: str, kind: str, **fields) -> dict:
        case = self.cases[case_ref]
        sequence = 1 + sum(
            record["entry"]["agreement"] == case["agreement"] for record in self.entries
        )
        entry = {
            **{key: case[key] for key in ("case_ref", "transaction", "agreement", "parts")},
            "actor": actor, "kind": kind, "at": self._clock,
            "issuer": self.data["keys"]["identity"], "sequence": sequence,
            "record_ref": "record-fixture-" + str(sequence), **fields,
        }
        signed = wire(sign_record(entry))
        self.entries.append(signed)
        return deepcopy(signed)
