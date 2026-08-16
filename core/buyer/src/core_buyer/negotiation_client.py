"""Buyer-as-pure-client negotiation library.

The buyer doesn't run a storefront or any HTTP server. They pick a
seller, open a negotiation via HTTP, loop round-by-round until the
thread ends, and return the outcome. Every request is authenticated by the
buyer's injected marketplace signer so the seller can authorize the complete
principal without requiring a chain wallet.

Public API:
    negotiate_with_seller(...) -> NegotiationOutcome

Per-round decisions go through ``market_policy.negotiation_middleware``
— same chain framework the seller uses. The buyer's default chain is
the pinned-shape guard plus the configured policy's middlewares; domain
plugins may add schema middlewares (e.g. the API-credits
``answer_key_challenge`` pass-through) via ``default_guards``.

Units: listings broadcast **per-unit** rates (per lease hour for VM
compute, per token for API credits). ``unit_count`` is the schema
plugin's per-unit→absolute seam — the number of priced units this deal
spans; once it is fixed at round 0 the whole negotiation runs on
absolute totals. The VM plugin passes ``duration_seconds / 3600``, the
API-credits plugin passes the requested token quantity.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Optional

from market_policy.negotiation_middleware import (
    NegotiationChainExhausted,
    NegotiationContext,
    NegotiationMiddleware,
    NegotiationRound,
    load_negotiation_chain,
    normalize_policies_by_escrow_kind_config,
    run_negotiation_chain,
)
from market_policy.scalar_policies import make_escrow_kind_dispatch_middleware
from market_core.schemas import (
    SettlementOption,
    SettlementPlan,
    SettlementSelection,
)
from market_identity import (
    EMPTY_BODY,
    AuthenticatedResponse,
    Identity,
    RequestEnvelope,
    Signer,
    TrustedIdentitySet,
    canonical_body_hash,
    sign_request,
    verify_response,
)


DEFAULT_MAX_ROUNDS = 10
logger = logging.getLogger(__name__)
_RL_POLICY_NAMES = {"rl", "erc20_rl", "native_token_rl", "erc1155_rl"}

DEFAULT_CHAIN_GUARDS: tuple[str, ...] = ("buyer_escrow_shape_guard",)

#: Hook a domain package installs (at import, like the storefront's
#: accepted-escrows synthesizer) so the chain loader can trigger
#: self-registration of optional middlewares the core cannot import —
#: today the VM plugin's torch RL strategy. Best-effort by contract.
_RL_MIDDLEWARE_REGISTRAR: Callable[[], None] | None = None


def set_rl_middleware_registrar(fn: Callable[[], None] | None) -> None:
    global _RL_MIDDLEWARE_REGISTRAR
    _RL_MIDDLEWARE_REGISTRAR = fn


def _maybe_register_rl_middleware() -> None:
    """Trigger self-registration of the RL middleware, if a domain
    package installed a registrar. Best-effort — if the strategy's
    dependencies aren't installed, the chain loader raises its own
    actionable KeyError pointing at the extras."""
    if _RL_MIDDLEWARE_REGISTRAR is None:
        return
    try:
        _RL_MIDDLEWARE_REGISTRAR()
    except Exception:
        pass


def _policy_names_need_rl(policy_names: list[str]) -> bool:
    return any(name in _RL_POLICY_NAMES for name in policy_names)


def _policy_map_needs_rl(policies_by_kind: dict[str, list[str]]) -> bool:
    return any(_policy_names_need_rl(names) for names in policies_by_kind.values())


def load_buyer_chain(
    *,
    policies: Any = None,
    policy_mode: str | None = None,
    default_guards: tuple[str, ...] = DEFAULT_CHAIN_GUARDS,
    chain_config_paths: (
        Mapping[str, str | None] | Callable[[], Mapping[str, str | None]] | None
    ) = None,
) -> list[NegotiationMiddleware]:
    """Load the buyer's negotiation chain.

    If ``policies`` is provided (from `[negotiation] policies = [...]`
    in `buyer.toml`), uses the explicit ordered list. Otherwise the
    chain is `[*default_guards, *policy.middlewares]` — the default
    guards open with the shape guard, which vetoes if the seller
    silently mutates a buyer-pinned opaque proposal field; a schema plugin may
    extend them (the API-credits plugin inserts its key-challenge
    pass-through); the policy is `policy_mode` if set, else the one
    buyer.toml `[negotiation] policy` names (default `listed_price`).
    Resolution failures raise — a typo'd policy name must not silently
    become some other policy.
    """
    policies_by_kind = normalize_policies_by_escrow_kind_config(policies)
    if policies_by_kind:
        if _policy_map_needs_rl(policies_by_kind):
            _maybe_register_rl_middleware()
        resolved_paths = (
            chain_config_paths() if callable(chain_config_paths) else chain_config_paths
        )
        config_paths = dict(resolved_paths or {})
        return load_negotiation_chain(list(default_guards)) + [
            make_escrow_kind_dispatch_middleware(
                policies_by_kind,
                chain_config_paths=config_paths,
            )
        ]

    if policies:
        names = [str(p).strip() for p in policies if str(p).strip()]
    elif (policy_mode or "").strip():
        names = [*default_guards, (policy_mode or "").strip()]
    else:
        # The configured BuyerPolicy names the rest of the chain
        # (buyer.toml [negotiation] policy, default listed_price).
        # Resolution failures propagate: silently substituting a
        # default here would negotiate under a policy the user never
        # chose.
        from .policy_surface import configured_buyer_policy

        try:
            policy = configured_buyer_policy(strict=True)
        except KeyError as exc:
            raise RuntimeError(str(exc)) from exc
        names = [*default_guards, *policy.middlewares]
    if _policy_names_need_rl(names):
        _maybe_register_rl_middleware()
    return load_negotiation_chain(names)


DEFAULT_TIMEOUT_SECONDS = 30.0


def _dump_payload(value: Any, *, mode: str | None = None) -> dict[str, Any]:
    """Serialize a core-facing opaque payload without importing its schema."""
    if isinstance(value, dict):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        kwargs = {"mode": mode} if mode is not None else {}
        dumped = model_dump(**kwargs)
        if isinstance(dumped, dict):
            return dumped
    raise TypeError("settlement payload must be a dictionary or model-dumpable value")


@dataclass
class NegotiationOutcome:
    """What came out of a full negotiation run from the buyer's POV.

    ``accepted_provision_terms`` and ``accepted_escrow_proposal``
    are populated when the seller echoed them back in the negotiation
    response (always on non-rejection paths). Settlement-time escrow
    construction reads from these — using the *seller-confirmed* values
    rather than the buyer's local proposal protects against any
    drift between sides.

    ``agreed_amount`` is the absolute total payment in base units of
    the escrow's payment token (i.e. ``accepted_escrow_proposal.fields
    ["amount"]``). Per-unit rates only exist as listing broadcasts;
    once a negotiation starts everything is absolute. ``unit_count``
    echoes the buyer's ask from negotiation init (None on resume,
    where the prior run-log is the source of truth).
    """

    status: str  # "agreed" | "exited"
    negotiation_id: Optional[str]  # None only if /new itself failed
    agreed_amount: Optional[int] = None
    unit_count: Optional[float] = None
    reason: Optional[str] = None  # populated on exit
    rounds: int = 0
    accepted_provision_terms: Any | None = None
    accepted_escrow_proposal: Any | None = None
    settlement_selection: Optional[SettlementSelection] = None
    settlement_plan: Optional[SettlementPlan] = None
    # Legacy mechanism-specific terms remain opaque at the core boundary.
    accepted_escrow_terms: Optional[list[Any]] = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"status": self.status, "rounds": self.rounds}
        if self.negotiation_id is not None:
            d["negotiation_id"] = self.negotiation_id
        if self.agreed_amount is not None:
            d["agreed_amount"] = self.agreed_amount
        if self.unit_count is not None:
            d["unit_count"] = self.unit_count
        if self.reason is not None:
            d["reason"] = self.reason
        if self.accepted_provision_terms is not None:
            d["accepted_provision_terms"] = _dump_payload(self.accepted_provision_terms)
        if self.accepted_escrow_proposal is not None:
            d["accepted_escrow_proposal"] = _dump_payload(self.accepted_escrow_proposal)
        if self.settlement_selection is not None:
            d["settlement_selection"] = self.settlement_selection.model_dump()
        if self.settlement_plan is not None:
            d["settlement_plan"] = self.settlement_plan.model_dump()
        if self.accepted_escrow_terms is not None:
            d["accepted_escrow_terms"] = [
                _dump_payload(term) for term in self.accepted_escrow_terms
            ]
        return d


def parse_accepted_terms_from_reply(
    reply: dict[str, Any],
    *,
    decode_provision_terms: Callable[[dict[str, Any]], Any] | None = None,
    decode_escrow_proposal: Callable[[dict[str, Any]], Any] | None = None,
    decode_escrow_terms: Callable[[dict[str, Any]], Any] | None = None,
) -> tuple[
    Any | None,
    Any | None,
    Optional[SettlementSelection],
    Optional[SettlementPlan],
    Optional[list[Any]],
]:
    """Extract the seller's accepted state from a negotiate reply.

    Returns all-None on exit/reject paths.  The authoritative
    ``settlement_plan`` is never synthesized from another field.
    """
    raw_prov = reply.get("accepted_provision_terms")
    raw_esc = reply.get("accepted_escrow_proposal")
    raw_selection = reply.get("settlement_selection")
    raw_plan = reply.get("settlement_plan")
    raw_terms = reply.get("accepted_escrow_terms")
    prov = (
        decode_provision_terms(dict(raw_prov))
        if isinstance(raw_prov, dict) and decode_provision_terms is not None
        else dict(raw_prov)
        if isinstance(raw_prov, dict)
        else None
    )
    esc = (
        decode_escrow_proposal(dict(raw_esc))
        if isinstance(raw_esc, dict) and decode_escrow_proposal is not None
        else dict(raw_esc)
        if isinstance(raw_esc, dict)
        else None
    )
    selection = (
        SettlementSelection.model_validate(raw_selection)
        if isinstance(raw_selection, dict)
        else None
    )
    if isinstance(raw_terms, list):
        if not all(isinstance(item, dict) for item in raw_terms):
            raise ValueError("accepted_escrow_terms must contain objects")
        raw_term_dicts = [dict(item) for item in raw_terms]
    else:
        raw_term_dicts = None
    terms = (
        [
            decode_escrow_terms(term) if decode_escrow_terms is not None else term
            for term in raw_term_dicts
        ]
        if raw_term_dicts is not None
        else None
    )
    plan: Optional[SettlementPlan] = None
    if isinstance(raw_plan, dict):
        plan = SettlementPlan.model_validate(raw_plan)
    return prov, esc, selection, plan, terms


def _validate_selection_echo(
    actual: SettlementSelection | None,
    expected: SettlementSelection,
) -> None:
    if actual is None:
        raise RuntimeError(
            "seller accept state omitted the buyer-selected settlement option"
        )
    if actual != expected:
        raise RuntimeError(
            "seller settlement_selection differs from the buyer-selected "
            "advertised option"
        )


def _validate_accepted_provision_terms(
    actual: Any | None,
    expected: Any | None,
) -> None:
    if actual is None or expected is None:
        return
    if _dump_payload(actual, mode="json") != _dump_payload(expected, mode="json"):
        raise RuntimeError(
            "seller accepted_provision_terms differ from the buyer-requested terms"
        )


def _validated_party(
    value: Any,
    *,
    field: str,
) -> Identity:
    try:
        return Identity.model_validate(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"seller accept state has invalid {field}") from exc


def _validate_settlement_acceptance(
    *,
    reply: Mapping[str, Any],
    selection: SettlementSelection | None,
    plan: SettlementPlan | None,
    expected_selection: SettlementSelection,
    advertised_option: SettlementOption | None,
    agreed_amount: int,
    expected_plan: SettlementPlan | None,
    buyer_principal: Identity,
    trusted_seller_principals: TrustedIdentitySet,
    validate_advertised_plan: Callable[[SettlementPlan], None] | None,
) -> None:
    """Correlate a signed terminal reply with the buyer's exact commitment."""

    _validate_selection_echo(selection, expected_selection)
    if plan is None:
        raise RuntimeError("seller accept state omitted the settlement_plan")

    reply_buyer = _validated_party(
        reply.get("buyer_principal"),
        field="buyer_principal",
    )
    reply_seller = _validated_party(
        reply.get("seller_principal"),
        field="seller_principal",
    )
    if reply_buyer != buyer_principal:
        raise RuntimeError("seller accept state substituted the buyer principal")
    if reply_seller not in trusted_seller_principals:
        raise RuntimeError("seller accept state names an untrusted seller principal")

    plan_buyer = _validated_party(
        plan.buyer_principal,
        field="settlement_plan.buyer_principal",
    )
    plan_seller = _validated_party(
        plan.seller_principal,
        field="settlement_plan.seller_principal",
    )
    if plan_buyer != buyer_principal or plan_seller != reply_seller:
        raise RuntimeError("seller settlement_plan substituted an accepted party")
    if len(plan.obligations) != 1:
        raise RuntimeError(
            "seller settlement_plan does not describe exactly one selected obligation"
        )

    obligation = plan.obligations[0]
    if obligation.payer != "buyer" or obligation.claimant != "seller":
        raise RuntimeError("seller settlement_plan changed payer/claimant semantics")
    payer_principal = _validated_party(
        obligation.payer_principal,
        field="settlement_plan.obligations[0].payer_principal",
    )
    claimant_principal = _validated_party(
        obligation.claimant_principal,
        field="settlement_plan.obligations[0].claimant_principal",
    )
    if payer_principal != buyer_principal or claimant_principal != reply_seller:
        raise RuntimeError(
            "seller settlement_plan obligation substituted an accepted party"
        )
    if obligation.mechanism != expected_selection.mechanism:
        raise RuntimeError(
            "seller settlement_plan mechanism differs from the selected option"
        )
    if obligation.amount != agreed_amount:
        raise RuntimeError(
            "seller settlement_plan amount differs from the negotiated amount"
        )
    if obligation.expiration_unix != expected_selection.expiration_unix:
        raise RuntimeError(
            "seller settlement_plan expiry differs from the buyer selection"
        )

    if advertised_option is None and expected_plan is None:
        raise RuntimeError(
            "buyer acceptance state omitted the advertised settlement semantics"
        )
    if expected_plan is not None:
        if len(expected_plan.obligations) != 1:
            raise RuntimeError(
                "persisted accepted settlement plan is not a single obligation"
            )
        expected_obligation = expected_plan.obligations[0].model_copy(
            update={"amount": agreed_amount}
        )
        expected_semantic_plan = expected_plan.model_copy(
            update={"obligations": [expected_obligation]}
        )
        if plan != expected_semantic_plan:
            raise RuntimeError(
                "seller settlement_plan semantics differ from persisted accepted terms"
            )
        return
    assert advertised_option is not None
    if (
        advertised_option.option_id != expected_selection.option_id
        or advertised_option.mechanism != expected_selection.mechanism
    ):
        raise RuntimeError(
            "buyer settlement selection does not identify the advertised option"
        )
    if obligation.asset != advertised_option.asset:
        raise RuntimeError(
            "seller settlement_plan asset differs from the advertised option"
        )
    if validate_advertised_plan is not None:
        validate_advertised_plan(plan)
        return
    expected_params = dict(advertised_option.params)
    expected_params["payer_principal"] = buyer_principal.model_dump(mode="json")
    expected_params["claimant_principal"] = reply_seller.model_dump(mode="json")
    if obligation.params != expected_params:
        raise RuntimeError(
            "seller settlement_plan params differ from the advertised option"
        )
    condition = advertised_option.params.get("condition")
    expected_conditions = [dict(condition)] if isinstance(condition, Mapping) else []
    if obligation.conditions != expected_conditions or plan.service_terms:
        raise RuntimeError(
            "seller settlement_plan semantics differ from the advertised option"
        )


_SIGNATURE_VERSION_HEADER = "X-Market-Signature-Version"
_IDENTITY_SCHEME_HEADER = "X-Market-Identity-Scheme"
_IDENTITY_IDENTIFIER_HEADER = "X-Market-Identity-Identifier"
_ROLE_HEADER = "X-Market-Role"
_REQUEST_ID_HEADER = "X-Market-Request-ID"
_TIMESTAMP_HEADER = "X-Market-Timestamp"
_SIGNATURE_HEADER = "X-Market-Signature"
_MAX_RESPONSE_SKEW = 300


def _header(headers: Mapping[str, str] | Any, name: str) -> str | None:
    value = headers.get(name) if headers is not None else None
    if value is not None:
        return str(value)
    if headers is None:
        return None
    lowered = name.lower()
    for key, candidate in headers.items():
        if str(key).lower() == lowered:
            return str(candidate)
    return None


def _authenticated_json(
    url: str,
    body: dict[str, Any] | None,
    *,
    signer: Signer,
    principal: Identity,
    method: str,
    operation: str,
    resource: str,
    expected_response_principals: TrustedIdentitySet,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    request_id: str | None = None,
    timestamp: int | None = None,
    expected_response_role: str = "seller",
) -> dict[str, Any]:
    """Send one v2-authenticated JSON request and verify a pinned response."""

    if signer.identity != principal:
        raise ValueError("buyer signer identity does not match request principal")
    if not isinstance(expected_response_principals, TrustedIdentitySet):
        raise ValueError("a pinned response principal set is required")
    request_id = request_id or uuid.uuid4().hex
    timestamp = int(time.time()) if timestamp is None else timestamp
    body_value: Any = EMPTY_BODY if body is None else body
    authenticated = sign_request(
        signer=signer,
        envelope=RequestEnvelope(
            role="buyer",
            principal=principal,
            method=method,
            operation=operation,
            resource=resource,
            request_id=request_id,
            timestamp=timestamp,
            body_hash=canonical_body_hash(body_value),
        ),
    )
    headers = {
        "Accept": "application/json",
        _SIGNATURE_VERSION_HEADER: authenticated.protocol,
        _IDENTITY_SCHEME_HEADER: authenticated.principal.scheme.value,
        _IDENTITY_IDENTIFIER_HEADER: authenticated.principal.identifier,
        _ROLE_HEADER: authenticated.role,
        _REQUEST_ID_HEADER: authenticated.request_id,
        _TIMESTAMP_HEADER: str(authenticated.timestamp),
        _SIGNATURE_HEADER: authenticated.proof.value,
    }
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(
            body,
            separators=(",", ":"),
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8")
            response_headers = getattr(resp, "headers", None)
            response_status = int(getattr(resp, "status", 200))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        response_headers = getattr(exc, "headers", None)
        response_status = int(exc.code)
    except Exception as exc:
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc

    if text:
        try:
            payload = json.loads(text)
        except ValueError as exc:
            raise RuntimeError(
                f"{method} {url} returned non-JSON: {text[:200]!r}"
            ) from exc
    else:
        payload = {}

    try:
        signed_response = AuthenticatedResponse.model_validate(
            {
                "protocol": _header(response_headers, _SIGNATURE_VERSION_HEADER),
                "role": _header(response_headers, _ROLE_HEADER),
                "principal": {
                    "scheme": _header(response_headers, _IDENTITY_SCHEME_HEADER),
                    "identifier": _header(
                        response_headers, _IDENTITY_IDENTIFIER_HEADER
                    ),
                },
                "method": method,
                "operation": operation,
                "resource": resource,
                "request_id": _header(response_headers, _REQUEST_ID_HEADER),
                "timestamp": int(_header(response_headers, _TIMESTAMP_HEADER) or ""),
                "status": response_status,
                "body_hash": canonical_body_hash(payload if text else EMPTY_BODY),
                "proof": {
                    "scheme": _header(response_headers, _IDENTITY_SCHEME_HEADER),
                    "value": _header(response_headers, _SIGNATURE_HEADER),
                },
            }
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            f"{method} {url} returned malformed or legacy response authentication"
        ) from exc
    verification = verify_response(
        signed_response,
        body=payload if text else EMPTY_BODY,
        now=int(time.time()),
        max_skew=_MAX_RESPONSE_SKEW,
        expected_role=expected_response_role,
        expected_principals=expected_response_principals,
        expected_method=method,
        expected_operation=operation,
        expected_resource=resource,
        expected_request_id=request_id,
    )
    if not verification.verified:
        raise RuntimeError(
            f"{method} {url} response authentication failed: {verification.code.value}"
        )
    if not 200 <= response_status < 300:
        raise RuntimeError(
            f"{method} {url} -> authenticated HTTP {response_status}: {text[:500]}"
        )
    if not isinstance(payload, dict):
        raise RuntimeError(f"{method} {url} returned non-object JSON")
    return payload


@dataclass
class ResumeState:
    """Inputs for resuming an in-flight negotiation thread.

    Built by ``market negotiate --from <run_id>``: the run-log gives
    us the server-assigned ``negotiation_id``, the rounds we've
    observed, and the seller's last-known proposal. We replay that
    into the strategy and continue the round loop without going through
    ``/api/v1/negotiate/new`` again (the seller has the thread already).
    """

    negotiation_id: str
    transcript: list[NegotiationRound]
    last_seller_proposal: dict | None
    rounds_completed: int
    accepted_provision_terms: dict[str, Any] | None = None
    settlement_plan: dict[str, Any] | None = None
    accepted_escrow_proposal: dict[str, Any] | None = None
    settlement_selection: dict[str, Any] | None = None
    accepted_escrow_terms: list[dict[str, Any]] | None = None


def negotiate_with_seller(
    *,
    seller_url: str,
    principal: Identity,
    signer: Signer,
    listing_id: str,
    resolve_seller_principals: Callable[[], TrustedIdentitySet],
    initial_price: float,
    max_price: float,
    unit_count: Optional[float] = None,
    provision_terms: Any | None = None,
    escrow_proposal: Any | None = None,
    encode_escrow_proposal: Callable[[Any], dict[str, Any]] | None = None,
    decode_provision_terms: Callable[[dict[str, Any]], Any] | None = None,
    decode_escrow_proposal: Callable[[dict[str, Any]], Any] | None = None,
    decode_escrow_terms: Callable[[dict[str, Any]], Any] | None = None,
    settlement_selection: Optional[SettlementSelection] = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    on_round: Optional[Callable[[int, dict, dict], None]] = None,
    chain: Optional[list[NegotiationMiddleware]] = None,
    default_guards: tuple[str, ...] = DEFAULT_CHAIN_GUARDS,
    resume: Optional[ResumeState] = None,
    policy_params: Optional[dict[str, Any]] = None,
    validate_advertised_plan: Callable[[SettlementPlan], None] | None = None,
) -> NegotiationOutcome:
    """Run a synchronous negotiation with one seller, round-by-round.

    `initial_price` is what the buyer opens with (can be lower than max
    to haggle). `max_price` is the buyer's absolute ceiling — any seller
    counter at or below convergence to this gets accepted. Both are
    **per-unit** rates; ``unit_count`` scales them to the absolute
    amounts the negotiation runs on, and is required (> 0) for fresh
    starts — the schema plugin owns the translation (lease hours for
    compute, token quantity for credits). In resume mode the prices are
    treated as absolute (the prior run fixed the totals).

    `provision_terms` describes what the buyer wants the seller to
    deliver (the schema-tagged off-chain payload) and `escrow_proposal`
    is the buyer's proposed on-chain escrow tuple — picks one of the
    listing's ``accepted_escrows`` entries by ``(chain_name,
    escrow_address)`` and supplies the buyer-committable EscrowData
    in ``fields`` plus ``expiration_unix``. Both are sent on
    /api/v1/negotiate/new and validated server-side against the
    listing's acceptance set. Required for fresh starts; ignored in
    resume mode (the negotiation thread already has them committed).

    The negotiation_id is server-assigned (returned in the
    /api/v1/negotiate/new response) and threaded through every subsequent
    /negotiate/{neg_id} round; the buyer doesn't supply it.

    `on_round(round_idx, our_msg, their_reply)` is an optional observer
    hook (for CLI rendering, testing).

    `validate_advertised_plan` may validate a domain projection that intentionally
    moves domain-only option fields into service terms. Universal party, amount,
    asset, mechanism, and expiry checks always run first; the callback owns the
    remaining obligation params, conditions, and service-term correspondence.

    Synchronous everything: the seller responds in-line on each POST.
    Returns a NegotiationOutcome describing how it ended; the seller's
    accepted_* echo is parsed back so settlement-time escrow construction
    can use the agreed (not local-proposed) values.
    """
    seller_url = seller_url.rstrip("/")
    if signer.identity != principal:
        raise ValueError("buyer signer identity does not match negotiation principal")
    transcript: list[NegotiationRound] = []
    # Captured from the seller's round-0 response and threaded forward.
    # The seller commits to these at /negotiate/new (they're persisted on
    # the negotiation thread); subsequent rounds don't re-echo them.
    accepted_prov: Any | None = None
    accepted_esc: Any | None = None
    accepted_selection: Optional[SettlementSelection] = None
    accepted_plan: Optional[SettlementPlan] = None
    accepted_terms: Optional[list[Any]] = None

    def _parse_reply(
        reply_payload: dict[str, Any],
    ) -> tuple[
        Any | None,
        Any | None,
        SettlementSelection | None,
        SettlementPlan | None,
        list[Any] | None,
    ]:
        return parse_accepted_terms_from_reply(
            reply_payload,
            decode_provision_terms=decode_provision_terms,
            decode_escrow_proposal=decode_escrow_proposal,
            decode_escrow_terms=decode_escrow_terms,
        )

    negotiation_policy_params = dict(policy_params or {})
    raw_advertised_option = negotiation_policy_params.pop(
        "_selected_settlement_option",
        None,
    )
    advertised_option = (
        SettlementOption.model_validate(raw_advertised_option)
        if raw_advertised_option is not None
        else None
    )
    expected_selection = settlement_selection

    if resume is not None:
        (
            accepted_prov,
            accepted_esc,
            accepted_selection,
            accepted_plan,
            accepted_terms,
        ) = _parse_reply(
            {
                "settlement_plan": resume.settlement_plan,
                "accepted_provision_terms": resume.accepted_provision_terms,
                "accepted_escrow_proposal": resume.accepted_escrow_proposal,
                "settlement_selection": resume.settlement_selection,
                "accepted_escrow_terms": resume.accepted_escrow_terms,
            }
        )
        expected_selection = accepted_selection
    if advertised_option is not None and expected_selection is not None:
        if (
            advertised_option.option_id != expected_selection.option_id
            or advertised_option.mechanism != expected_selection.mechanism
        ):
            raise RuntimeError(
                "buyer settlement selection does not identify the advertised option"
            )

    if resume is not None:
        unit_count = None  # absolute bounds; the prior run fixed the totals
    if chain is None:
        chain = load_buyer_chain(default_guards=default_guards)

    # Pinned proposal: the buyer's first-round proposal — every field
    # set here is a buyer commitment the seller may not mutate. Used by
    # ``buyer_escrow_shape_guard`` in the chain.
    pinned_proposal: dict[str, Any] | None = None

    def _amount(p: dict | None) -> int | None:
        if not isinstance(p, dict):
            return None
        v = (p.get("fields") or {}).get("amount")
        return int(v) if v is not None else None

    neg_id: str | None
    if resume is not None:
        # Resume mode: skip /api/v1/negotiate/new and the first counter exchange.
        # We trust the run-log's recorded transcript and the seller's last
        # counter proposal; the strategy decides our next move from there.
        if resume.last_seller_proposal is None:
            raise RuntimeError(
                "Cannot resume — no seller counter proposal recorded in run-log."
            )
        neg_id = resume.negotiation_id
        transcript = list(resume.transcript)
        # Synthesize a `reply` dict shaped like the round-loop expects.
        reply: dict[str, Any] = {
            "negotiation_id": neg_id,
            "action": "counter",
            "proposal": resume.last_seller_proposal,
        }
        # Recover the buyer's first-pinned proposal from the transcript.
        for entry in transcript:
            if entry.sender == "us" and entry.proposal is not None:
                pinned_proposal = entry.proposal
                break
        round_idx = max(1, resume.rounds_completed)
    else:
        # --- Round 0: /api/v1/negotiate/new ---------------------------------------
        if provision_terms is None:
            raise RuntimeError(
                "provision_terms is required for fresh negotiations "
                "(the schema-tagged payload describing what the seller "
                "will provision)"
            )
        if (escrow_proposal is None) == (settlement_selection is None):
            raise RuntimeError(
                "exactly one of escrow_proposal or settlement_selection is "
                "required for fresh negotiations"
            )
        # Translate per-unit bounds → absolute amounts (× unit_count).
        # Listings broadcast per-unit rates; once the unit count is
        # fixed, the whole negotiation runs on absolute totals.
        if unit_count is None or unit_count <= 0:
            raise RuntimeError(
                "unit_count must be > 0 to translate per-unit bounds "
                "into absolute amounts."
            )
        scale = float(unit_count)
        initial_amount = int(round(float(initial_price) * scale))
        ceiling_amount = float(max_price) * scale

        # Pin the buyer's first proposal: the policy chain owns the
        # round-0 opening (ARCHITECTURE.md, "Buyer negotiation policy surface") — run it
        # on an empty history and pin its proposal. Whether and where an
        # opening amount lands in the fields is the configured policy's
        # compatibility knowledge, not this loop's.
        if settlement_selection is not None:
            base_proposal = {
                "settlement_selection": settlement_selection.model_dump(),
                "fields": {},
            }
        else:
            assert escrow_proposal is not None
            if encode_escrow_proposal is None:
                raise RuntimeError(
                    "the selected settlement mechanism must inject an "
                    "escrow proposal encoder"
                )
            base_proposal = encode_escrow_proposal(escrow_proposal)
        if expected_selection is None and advertised_option is not None:
            raw_expiration = base_proposal.get("expiration_unix")
            if isinstance(raw_expiration, bool) or not isinstance(raw_expiration, int):
                raise RuntimeError(
                    "selected advertised settlement option has no pinned expiry"
                )
            expected_selection = SettlementSelection(
                mechanism=advertised_option.mechanism,
                option_id=advertised_option.option_id,
                expiration_unix=raw_expiration,
            )
        opening = run_negotiation_chain(
            chain,
            [],
            NegotiationContext(
                direction="minimize",
                our_reference_amount=ceiling_amount,
                our_opening_amount=initial_amount,
                our_escrow_proposal=base_proposal,
                max_rounds=max_rounds,
                intermediate=negotiation_policy_params,
            ),
        )
        # The decision is honored, not second-guessed: a chain that
        # exits/rejects before opening means this buyer does not open
        # this negotiation — the seller is never contacted.
        if opening.action in ("exit", "reject"):
            return NegotiationOutcome(
                status="exited",
                negotiation_id=None,
                reason=opening.reason or f"buyer_{opening.action}_at_opening",
                unit_count=unit_count,
                rounds=0,
            )
        if opening.action != "counter" or opening.proposal is None:
            raise RuntimeError(
                f"Policy chain produced {opening.action!r} as the round-0 "
                f"opening — only counter (with a proposal), exit, or "
                f"reject make sense before the seller has said anything."
            )
        pinned_proposal = opening.proposal

        new_body = {
            "listing_id": listing_id,
            "buyer_principal": principal.model_dump(mode="json"),
            "provision_terms": _dump_payload(provision_terms, mode="json"),
            "proposal": pinned_proposal,
        }
        trusted_seller_principals = resolve_seller_principals()
        reply = _authenticated_json(
            f"{seller_url}/api/v1/negotiate/new",
            new_body,
            signer=signer,
            principal=principal,
            method="POST",
            operation="negotiate_new",
            resource=listing_id,
            expected_response_principals=trusted_seller_principals,
        )

        raw_neg_id = reply.get("negotiation_id")
        neg_id = raw_neg_id if isinstance(raw_neg_id, str) and raw_neg_id else None
        seller_action = reply.get("action")
        (
            accepted_prov,
            accepted_esc,
            accepted_selection,
            accepted_plan,
            accepted_terms,
        ) = _parse_reply(reply)
        if seller_action in {"counter", "accept"} and accepted_prov is None:
            raise RuntimeError(
                "seller negotiation reply omitted accepted_provision_terms"
            )
        _validate_accepted_provision_terms(accepted_prov, provision_terms)
        if expected_selection is not None and seller_action in {"counter", "accept"}:
            _validate_selection_echo(accepted_selection, expected_selection)
        agreed_amount = _amount(reply.get("proposal"))
        if agreed_amount is None:
            agreed_amount = initial_amount
        if seller_action in {"counter", "accept"} and expected_selection is not None:
            _validate_settlement_acceptance(
                reply=reply,
                selection=accepted_selection,
                plan=accepted_plan,
                expected_selection=expected_selection,
                advertised_option=advertised_option,
                expected_plan=None,
                agreed_amount=agreed_amount,
                buyer_principal=principal,
                trusted_seller_principals=trusted_seller_principals,
                validate_advertised_plan=validate_advertised_plan,
            )
        if on_round:
            on_round(0, new_body, reply)

        if seller_action == "accept":
            return NegotiationOutcome(
                status="agreed",
                negotiation_id=neg_id,
                agreed_amount=agreed_amount,
                unit_count=unit_count,
                rounds=0,
                accepted_provision_terms=accepted_prov,
                accepted_escrow_proposal=accepted_esc,
                settlement_selection=accepted_selection,
                settlement_plan=accepted_plan,
                accepted_escrow_terms=accepted_terms,
            )
        # On non-agreed paths we still carry forward what the seller
        # validated — used if the negotiation ends up agreed in later
        # rounds (seller doesn't re-echo accepted_* on /continue).
        if seller_action in ("exit", "reject"):
            return NegotiationOutcome(
                status="exited",
                negotiation_id=neg_id,
                reason=reply.get("reason"),
                unit_count=unit_count,
                rounds=0,
            )
        # From here on seller_action should be "counter".
        if seller_action != "counter":
            raise RuntimeError(
                f"Unexpected seller action on /api/v1/negotiate/new: {seller_action!r}"
            )
        if not neg_id:
            raise RuntimeError(
                "/api/v1/negotiate/new returned counter but no negotiation_id"
            )

        transcript.append(
            NegotiationRound(
                round_number=0,
                sender="us",
                action="initial",
                proposal=pinned_proposal,
            )
        )
        seller_round0_proposal = reply.get("proposal")
        transcript.append(
            NegotiationRound(
                round_number=0,
                sender="them",
                action="counter",
                proposal=seller_round0_proposal
                if isinstance(seller_round0_proposal, dict)
                else None,
            )
        )
        round_idx = 1

    # --- Rounds 1..N: /negotiate/{id} ----------------------------------
    while round_idx <= max_rounds:
        seller_counter_proposal = reply.get("proposal")
        if not isinstance(seller_counter_proposal, dict):
            raise RuntimeError(f"Seller counter without proposal: {reply!r}")

        # Append the seller's current counter to history so the chain
        # sees it as their_last_proposal.
        round_history = list(transcript)
        if not round_history or round_history[-1].sender != "them":
            round_history.append(
                NegotiationRound(
                    round_number=len(round_history),
                    sender="them",
                    action="counter",
                    proposal=seller_counter_proposal,
                )
            )
        ceiling_amount = (
            float(max_price) * float(unit_count)
            if unit_count is not None
            else float(max_price)
        )
        ctx = NegotiationContext(
            direction="minimize",
            our_reference_amount=ceiling_amount,
            our_opening_amount=(
                float(initial_price) * float(unit_count)
                if unit_count is not None
                else float(initial_price)
            ),
            listing={},
            our_escrow_proposal=pinned_proposal,
            available_resources={},
            max_rounds=max_rounds,
            intermediate=negotiation_policy_params,
        )
        try:
            next_move = run_negotiation_chain(chain, round_history, ctx)
        except NegotiationChainExhausted:
            # Local misconfiguration — but the seller's thread is live.
            # Release it with a protocol-level exit before erroring, so
            # the seller isn't left holding state until a watchdog.
            try:
                _authenticated_json(
                    f"{seller_url}/api/v1/negotiate/{neg_id}",
                    {
                        "action": "exit",
                        "reason": "buyer_chain_no_decision",
                        "buyer_principal": principal.model_dump(mode="json"),
                    },
                    signer=signer,
                    principal=principal,
                    method="POST",
                    operation="negotiate_continue",
                    resource=neg_id,
                    expected_response_principals=resolve_seller_principals(),
                )
            except Exception as notify_exc:
                logger.warning(
                    "Could not deliver the no-decision exit to the seller: %s",
                    notify_exc,
                )
            raise

        body: dict[str, Any] = {
            "action": next_move.action,
            "buyer_principal": principal.model_dump(mode="json"),
        }
        if next_move.action in ("counter", "accept"):
            if next_move.proposal is None:
                raise RuntimeError(
                    f"chain returned {next_move.action!r} without a proposal"
                )
            body["proposal"] = next_move.proposal
        elif next_move.action in ("exit", "reject"):
            body["reason"] = next_move.reason or "buyer_exit"

        trusted_seller_principals = resolve_seller_principals()
        reply = _authenticated_json(
            f"{seller_url}/api/v1/negotiate/{neg_id}",
            body,
            signer=signer,
            principal=principal,
            method="POST",
            operation="negotiate_continue",
            resource=neg_id,
            expected_response_principals=trusted_seller_principals,
        )

        # If our chain rejected (shape guard veto), the buyer terminates
        # locally without trusting any seller reply.
        if next_move.action == "reject":
            if on_round:
                on_round(round_idx, body, reply)
            return NegotiationOutcome(
                status="exited",
                negotiation_id=neg_id,
                reason=next_move.reason or "buyer_reject",
                unit_count=unit_count,
                rounds=round_idx,
            )

        # After we sent our move, the seller has replied with either
        # a matching terminal (accept/exit) or a further counter.
        if next_move.action == "accept":
            # We told the seller we accept; their reply should echo accept.
            if reply.get("action") == "accept":
                (
                    reply_prov,
                    reply_esc,
                    reply_selection,
                    reply_plan,
                    reply_terms,
                ) = _parse_reply(reply)
                _validate_accepted_provision_terms(reply_prov, accepted_prov)
                agreed_amount = _amount(reply.get("proposal"))
                if agreed_amount is None:
                    agreed_amount = _amount(next_move.proposal)
                if expected_selection is not None:
                    if agreed_amount is None:
                        raise RuntimeError(
                            "seller accept state omitted the negotiated amount"
                        )
                    _validate_settlement_acceptance(
                        reply=reply,
                        selection=reply_selection,
                        plan=reply_plan,
                        expected_selection=expected_selection,
                        advertised_option=advertised_option,
                        agreed_amount=agreed_amount,
                        expected_plan=accepted_plan if resume is not None else None,
                        buyer_principal=principal,
                        trusted_seller_principals=trusted_seller_principals,
                        validate_advertised_plan=validate_advertised_plan,
                    )
                if on_round:
                    on_round(round_idx, body, reply)
                return NegotiationOutcome(
                    status="agreed",
                    negotiation_id=neg_id,
                    agreed_amount=agreed_amount,
                    unit_count=unit_count,
                    rounds=round_idx,
                    accepted_provision_terms=reply_prov or accepted_prov,
                    accepted_escrow_proposal=reply_esc or accepted_esc,
                    settlement_selection=(
                        reply_selection
                        if expected_selection is not None
                        else reply_selection or accepted_selection
                    ),
                    settlement_plan=(
                        reply_plan
                        if expected_selection is not None
                        else reply_plan or accepted_plan
                    ),
                    accepted_escrow_terms=reply_terms or accepted_terms,
                )
            # Non-accept reply to our accept is anomalous but treat as terminal.
            if on_round:
                on_round(round_idx, body, reply)
            return NegotiationOutcome(
                status="exited",
                negotiation_id=neg_id,
                reason=f"seller_non_accept_after_buyer_accept:{reply.get('action')!r}",
                unit_count=unit_count,
                rounds=round_idx,
            )
        if next_move.action == "exit":
            if on_round:
                on_round(round_idx, body, reply)
            return NegotiationOutcome(
                status="exited",
                negotiation_id=neg_id,
                reason=next_move.reason or "buyer_exit",
                unit_count=unit_count,
                rounds=round_idx,
            )

        # next_move was counter → record both sides of this round.
        transcript.append(
            NegotiationRound(
                round_number=round_idx,
                sender="us",
                action="counter",
                proposal=next_move.proposal,
            )
        )
        seller_reply_action = reply.get("action") or "counter"
        seller_reply_proposal = reply.get("proposal")
        transcript.append(
            NegotiationRound(
                round_number=round_idx,
                sender="them",
                action=seller_reply_action
                if seller_reply_action in ("counter", "accept", "exit", "reject")
                else "counter",
                proposal=seller_reply_proposal
                if isinstance(seller_reply_proposal, dict)
                else None,
            )
        )

        seller_action = reply.get("action")
        if seller_action == "accept":
            (
                reply_prov,
                reply_esc,
                reply_selection,
                reply_plan,
                reply_terms,
            ) = _parse_reply(reply)
            _validate_accepted_provision_terms(reply_prov, accepted_prov)
            agreed_amount = _amount(seller_reply_proposal)
            if agreed_amount is None:
                agreed_amount = _amount(next_move.proposal)
            if expected_selection is not None:
                if agreed_amount is None:
                    raise RuntimeError(
                        "seller accept state omitted the negotiated amount"
                    )
                _validate_settlement_acceptance(
                    reply=reply,
                    selection=reply_selection,
                    plan=reply_plan,
                    expected_selection=expected_selection,
                    advertised_option=advertised_option,
                    expected_plan=accepted_plan if resume is not None else None,
                    agreed_amount=agreed_amount,
                    buyer_principal=principal,
                    trusted_seller_principals=trusted_seller_principals,
                    validate_advertised_plan=validate_advertised_plan,
                )
            if on_round:
                on_round(round_idx, body, reply)
            return NegotiationOutcome(
                status="agreed",
                negotiation_id=neg_id,
                agreed_amount=agreed_amount,
                unit_count=unit_count,
                rounds=round_idx,
                accepted_provision_terms=reply_prov or accepted_prov,
                accepted_escrow_proposal=reply_esc or accepted_esc,
                settlement_selection=(
                    reply_selection
                    if expected_selection is not None
                    else reply_selection or accepted_selection
                ),
                settlement_plan=(
                    reply_plan
                    if expected_selection is not None
                    else reply_plan or accepted_plan
                ),
                accepted_escrow_terms=reply_terms or accepted_terms,
            )
        if seller_action in ("exit", "reject"):
            if on_round:
                on_round(round_idx, body, reply)
            return NegotiationOutcome(
                status="exited",
                negotiation_id=neg_id,
                reason=reply.get("reason"),
                unit_count=unit_count,
                rounds=round_idx,
            )
        if seller_action != "counter":
            raise RuntimeError(
                f"Unexpected seller action mid-negotiation: {seller_action!r}"
            )
        if on_round:
            on_round(round_idx, body, reply)

        round_idx += 1

    # Hit max_rounds without converging.
    return NegotiationOutcome(
        status="exited",
        negotiation_id=neg_id,
        reason="max_rounds",
        unit_count=unit_count,
        rounds=max_rounds,
    )
