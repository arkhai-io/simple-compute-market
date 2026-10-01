"""A seller's asking rate per listing shape: declaration, contract, and resolution.

A Resource Pool may state, in its ``asking_rates`` policy tag, a price for each
listing shape it sells, keyed by offering mode:

    asking_rates:
      vm:
        - {shape: {gpu: {model: H100, count: 1}}, amount: "2.10", asset: usd, period: hour}

The rate is a listing attribute, not a settlement option rate: nothing is
constructed from it and it need not agree with any mechanism rate. Each entry
names the whole shape it prices, so it applies only to the listing whose shape
has the same canonical digest. An entry is keyed beside the shape rather than
inside it because a shape's digest is part of its listing's identity, and a price
change must refresh a listing in place, not replace it.

Three tiers resolve a listing's rate: the storefront's site-scoped override when
it states rates, otherwise the pool's declaration, otherwise none. An override's
rates replace the pool's as a whole list, and an empty list publishes no rate:
withholding a price is a commercial choice, unlike an empty shape list. There is
no configuration default, because a storefront-wide value would advertise one
party's price as another site's.

Validation is split by what each layer can know. Every pool-write surface checks
structure (``validate_asking_rates``), as it does for ``listing_shapes``. The
reading domain checks what only it can: that each shape is in its vocabulary,
that no two entries price one shape, and that each period is one this version
accepts. A declaration failing that holds the pool rather than falling through
to a lower tier, unlike the pricing hints, which treat a malformed field as
absent: dropping a price the seller believes they published is worse than not
publishing until it is fixed. See
openspec/specs/storefront-publication/spec.md.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from market_capability_shape import shape_structure_problems

ASKING_RATES_POLICY_TAG = "asking_rates"

#: The periods an asking rate may be quoted per in this version. Kept equal to
#: the time units settlement arithmetic can scale (``PER_UNIT_SECONDS``) by a
#: parity test rather than imported from it: widening this set is a decision
#: about what buyers compare, not a side effect of a new settlement unit.
ACCEPTED_ASKING_RATE_PERIODS: frozenset[str] = frozenset({"hour"})

#: The settlement publication clause's decimal-text grammar: no sign, no
#: exponent, no leading zeros. Exact text, so a price survives every hop
#: without passing through binary floating point.
_DECIMAL_AMOUNT = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
#: The settlement clause's unit grammar, so a period is spelled as a published
#: settlement unit is.
_UNIT = re.compile(r"[a-z][a-z0-9_-]*")
_ENTRY_KEYS = frozenset({"shape", "amount", "asset", "period"})

ASKING_RATE_SOURCE_OVERRIDE = "storefront_override"
ASKING_RATE_SOURCE_HINT = "pool_hint"
ASKING_RATE_SOURCE_NONE = "none"


@dataclass(frozen=True)
class AskingRate:
    """One price for one listing shape, as published."""

    amount: str
    asset: str
    period: str

    def published(self) -> dict[str, str]:
        return {"amount": self.amount, "asset": self.asset, "period": self.period}


def _amount_problem(value: Any) -> str | None:
    if not isinstance(value, str) or not _DECIMAL_AMOUNT.fullmatch(value):
        return "amount must be positive decimal text without a sign or an exponent"
    try:
        if Decimal(value) <= 0:
            return "amount must be positive decimal text without a sign or an exponent"
    except InvalidOperation:
        return "amount must be positive decimal text without a sign or an exponent"
    return None


def _token_problem(name: str, value: Any) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return f"{name} must be a non-empty string without surrounding whitespace"
    return None


def asking_rate_entry_problems(entry: Any) -> list[str]:
    """Structural problems with one entry, independent of any domain.

    The shape is checked only as a well-formed family-grouped shape and the
    period only as a token; whether either means anything is the reading
    domain's to say.
    """
    if not isinstance(entry, Mapping):
        return ["must be a mapping with shape, amount, asset, and period"]
    problems: list[str] = []
    missing = sorted(_ENTRY_KEYS - set(entry))
    if missing:
        problems.append(f"missing {', '.join(missing)}")
    unknown = sorted(str(key) for key in set(entry) - _ENTRY_KEYS)
    if unknown:
        problems.append(f"unknown {', '.join(unknown)}")
    if "shape" in entry:
        for problem in shape_structure_problems(entry["shape"]):
            where = f"shape.{problem.path}" if problem.path else "shape"
            problems.append(f"{where}: {problem.message}")
    if "amount" in entry and (problem := _amount_problem(entry["amount"])):
        problems.append(problem)
    if "asset" in entry and (problem := _token_problem("asset", entry["asset"])):
        problems.append(problem)
    if "period" in entry and (
        not isinstance(entry["period"], str) or not _UNIT.fullmatch(entry["period"])
    ):
        problems.append("period must be a canonical lowercase unit token")
    return problems


def validate_asking_rates(policy_tags: Mapping[str, Any]) -> list[str]:
    """Human-readable structural problems with a supplied ``asking_rates``.

    Empty means valid, including absent: the declaration is optional. A present
    value maps each offering mode to a list of entries. An empty list is
    accepted and prices nothing, as an absent mode does.
    """
    if ASKING_RATES_POLICY_TAG not in policy_tags:
        return []
    tag = ASKING_RATES_POLICY_TAG
    raw = policy_tags[tag]
    if not isinstance(raw, Mapping):
        return [f"{tag} must be a mapping of offering mode to a list of rates"]
    problems: list[str] = []
    for mode, entries in raw.items():
        if not isinstance(mode, str) or not mode:
            problems.append(f"{tag} offering modes must be non-empty strings, not {mode!r}")
            continue
        if not isinstance(entries, list):
            problems.append(f"{tag}.{mode} must be a list of rates")
            continue
        for index, entry in enumerate(entries):
            for problem in asking_rate_entry_problems(entry):
                problems.append(f"{tag}.{mode}[{index}]: {problem}")
    return problems


#: What ``raw_asking_rates`` returns when nothing is stated, as distinct from a
#: stated JSON ``null``, which is malformed and must not read as absent.
NOT_STATED: Any = object()


def raw_asking_rates(policy_tags: Mapping[str, Any], offering_mode: str) -> Any:
    """The unvalidated rate list a pool states for ``offering_mode``.

    ``NOT_STATED`` when the pool carries no ``asking_rates`` key, or the key
    names no entry for this mode. Anything stated is returned as-is, including
    ``None`` and a value that is not a mapping, so the resolver can report it
    unreadable rather than read it as absent.
    """
    if ASKING_RATES_POLICY_TAG not in policy_tags:
        return NOT_STATED
    declared = policy_tags[ASKING_RATES_POLICY_TAG]
    if not isinstance(declared, Mapping):
        return declared
    if offering_mode not in declared:
        return NOT_STATED
    return declared[offering_mode]


@dataclass(frozen=True)
class AskingRateResolution:
    """A pool's rates by shape digest and where they came from, or why they
    cannot be read."""

    source: str
    rates: Mapping[str, AskingRate] = field(default_factory=dict)
    shapes: Mapping[str, Any] = field(default_factory=dict)
    problems: tuple[str, ...] = ()

    @property
    def unreadable(self) -> bool:
        return bool(self.problems)

    def rate_for(self, shape_digest: str) -> AskingRate | None:
        return self.rates.get(shape_digest)

    def unpublished(self, published_digests: Iterable[str]) -> dict[str, Any]:
        """Each priced shape no published listing has, by digest.

        Such an entry has no effect; it is reported so a seller can see that a
        price they stated reached no buyer.
        """
        published = set(published_digests)
        return {
            digest: shape for digest, shape in self.shapes.items() if digest not in published
        }


def _resolve_stated(
    raw: Any,
    *,
    source: str,
    shape_digest: Callable[[Any], str],
    shape_problems: Callable[[Any], Iterable[str]],
    accepted_periods: frozenset[str],
) -> AskingRateResolution:
    if not isinstance(raw, list):
        return AskingRateResolution(source, problems=("must be a list of rates",))
    problems: list[str] = []
    rates: dict[str, AskingRate] = {}
    shapes: dict[str, Any] = {}
    for index, entry in enumerate(raw):
        entry_problems = asking_rate_entry_problems(entry)
        if not entry_problems:
            entry_problems = [f"shape: {problem}" for problem in shape_problems(entry["shape"])]
        if not entry_problems and entry["period"] not in accepted_periods:
            accepted = ", ".join(sorted(accepted_periods))
            entry_problems = [f"period must be one of: {accepted}"]
        if entry_problems:
            problems.extend(f"[{index}] {problem}" for problem in entry_problems)
            continue
        digest = shape_digest(entry["shape"])
        if digest in rates:
            problems.append(f"[{index}] prices a shape an earlier entry already prices")
            continue
        rates[digest] = AskingRate(
            amount=entry["amount"], asset=entry["asset"], period=entry["period"]
        )
        shapes[digest] = entry["shape"]
    if problems:
        return AskingRateResolution(source, problems=tuple(problems))
    return AskingRateResolution(source, rates=rates, shapes=shapes)


def resolve_asking_rates(
    policy_tags: Mapping[str, Any],
    offering_mode: str,
    *,
    override_rates: Any,
    shape_digest: Callable[[Any], str],
    shape_problems: Callable[[Any], Iterable[str]],
    accepted_periods: frozenset[str] = ACCEPTED_ASKING_RATE_PERIODS,
) -> AskingRateResolution:
    """A pool's asking rates: the override's, else the pool's, else none.

    ``override_rates`` is the stored override's rate list, or ``None`` when the
    override states none. ``shape_digest`` and ``shape_problems`` are the
    reading domain's: the digest must be the one its listings' identities use,
    so an entry matches exactly the listing whose shape it names.
    """
    resolve = dict(
        shape_digest=shape_digest,
        shape_problems=shape_problems,
        accepted_periods=accepted_periods,
    )
    if override_rates is not None:
        return _resolve_stated(override_rates, source=ASKING_RATE_SOURCE_OVERRIDE, **resolve)
    declared = raw_asking_rates(policy_tags, offering_mode)
    if declared is NOT_STATED:
        return AskingRateResolution(ASKING_RATE_SOURCE_NONE)
    if not isinstance(policy_tags[ASKING_RATES_POLICY_TAG], Mapping):
        return AskingRateResolution(
            ASKING_RATE_SOURCE_HINT,
            problems=("must be a mapping of offering mode to a list of rates",),
        )
    return _resolve_stated(declared, source=ASKING_RATE_SOURCE_HINT, **resolve)


__all__ = [
    "ACCEPTED_ASKING_RATE_PERIODS",
    "ASKING_RATES_POLICY_TAG",
    "ASKING_RATE_SOURCE_HINT",
    "ASKING_RATE_SOURCE_NONE",
    "ASKING_RATE_SOURCE_OVERRIDE",
    "AskingRate",
    "NOT_STATED",
    "AskingRateResolution",
    "asking_rate_entry_problems",
    "raw_asking_rates",
    "resolve_asking_rates",
    "validate_asking_rates",
]
