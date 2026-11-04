"""Strict playback of producer rulings; no claim selection or remedy arithmetic.

The injected payments peer executes the published calls. Inputs and checkpoint
boundaries, rather than wall-clock ordering, control visibility of signed records.
"""

from collections.abc import Callable, Mapping
from copy import deepcopy
import json

import httpx
from market_identity import canonical_json

from .authority import MediationContractFake


class RulingTraceFake(MediationContractFake):
    def __init__(
        self, trace: dict, payments_call: Callable[[dict], None], *,
        input_keys: Mapping[str, str] | None = None,
    ):
        super().__init__()
        self.trace = deepcopy(trace)
        self.authority = deepcopy(
            trace["agreement"]["settlement"]["lifecycle"]["adjudication"]["dispute"]
        )
        self._payments_call = payments_call
        # Lifecycle keys are domain-separated hashes; producer inputs use readable keys.
        # Only this explicit input aliasing differs; payments event keys remain exact.
        self._input_keys = dict(input_keys or {})
        self._step = 0
        self._record_end = 0
        self.payments_calls: list[dict] = []

    def _input_record(self, item: dict) -> int:
        response = item["response"]
        if item["operation"] == "append":
            return response["record"]["entry"]["sequence"]
        case = response["case"]["case_ref"]
        return next(r["entry"]["sequence"] for r in self.trace["records"]
                    if r["entry"]["case_ref"] == case and r["entry"]["kind"] == "filed")

    def _advance(self) -> None:
        step = self.trace["timeline"][self._step]
        assert len(self.payments_calls) == step["payments_before"]
        for call in self.trace["payments_calls"][step["payments_before"]:step["payments_after"]]:
            self._payments_call(deepcopy(call))
            self.payments_calls.append(deepcopy(call))
        if "input" in step:
            self._record_end = self._input_record(self.trace["inputs"][step["input"]])
        else:
            following = next((s for s in self.trace["timeline"][self._step + 1:]
                              if "input" in s), None)
            self._record_end = (self._input_record(self.trace["inputs"][following["input"]]) - 1
                                if following else len(self.trace["records"]))
        self.entries = deepcopy(self.trace["records"][:self._record_end])
        for signed in self.entries:
            entry = signed["entry"]
            case = entry["case_ref"]
            self.cases[case] = {
                **{k: entry[k] for k in ("case_ref", "agreement", "transaction", "parts")},
                "state": "closed" if entry["kind"] == "closed" else "open",
            }
        self._step += 1

    def checkpoint(self, operation: str) -> dict | list:
        step = self.trace["timeline"][self._step]
        assert step["operation"] == operation and "checkpoint" in step
        checkpoint = self.trace["checkpoints"][step["checkpoint"]]
        self._advance()
        return deepcopy(checkpoint["response"])

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method != "POST":
            return super().handle(request)
        self.requests.append(request)
        actor = self.tokens.get(request.headers.get("Authorization", "").removeprefix("Bearer "))
        if actor is None:
            return httpx.Response(401, json={"code": "authentication_required"})
        payload = json.loads(request.content)
        key = (actor, request.headers["Idempotency-Key"], request.url.path)
        content = canonical_json(payload)
        prior = self.replays.get(key)
        if prior is not None:
            answer = prior[1] if prior[0] == content else {
                "status": "error", "code": "idempotency_conflict", "message": "key changed content",
            }
        else:
            step = self.trace["timeline"][self._step]
            item = self.trace["inputs"][step["input"]]
            assert actor == item["actor"]
            assert request.url.path == ("/cases" if item["operation"] == "file" else "/append")
            assert key[1] == self._input_keys.get(item["idempotency_key"], item["idempotency_key"])
            assert content == canonical_json(item["request"])
            self._advance()
            answer = deepcopy(item["response"])
            self.replays[key] = (content, deepcopy(answer))
        if self.lose_next_response:
            self.lose_next_response = False
            raise httpx.ReadError("injected loss after authority acknowledgement", request=request)
        return httpx.Response(200, json=answer)
