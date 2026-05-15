"""Pluggable across-seller aggregation: candidates + negotiate → one deal.

A buyer's "what should I buy?" decision spans several discovered
listings. The aggregation policy is the seam that owns that decision.
It receives the post-discovery candidates *and* a ``negotiate``
callback; it decides how many candidates to negotiate with, in what
order, in parallel or sequence, and which agreed deal to return.

Shape::

    NegotiateFn = Callable[[dict], Awaitable[NegotiationOutcome]]
    AggregationPolicy = Callable[
        [list[dict], NegotiateFn],
        Awaitable[tuple[dict, NegotiationOutcome] | None],
    ]

The policy returns ``(listing, outcome)`` for the winner — or ``None``
to abort settlement (no candidate met its bar). The orchestrator then
settles exactly that one pair. The policy is the only thing that
knows the comparison rule, so the orchestrator stays dumb.

Built-in flavors:

- ``best_price`` (default) — negotiate with *all* candidates in parallel,
  pick the lowest agreed_price. The canonical "comparison shopping"
  example. Default because the sequential alternatives give up the
  comparison's headline benefit (cross-seller price discovery) in
  exchange for slightly less per-buy work; with ``max_matches_to_try``
  bounding fan-out, the cost is acceptable.
- ``fastest_agreed`` — race all candidates in parallel, take whichever
  agrees first; cancel the rest. For "provision ASAP, price-insensitive"
  buys.
- ``cheapest_first`` — sort by advertised price, negotiate sequentially,
  first agreed wins. Pre-callback historical behavior. Useful when each
  negotiation has nontrivial side effects (audit-log reveal, future-price
  signaling) you want to minimize.
- ``registry_order`` — pass through in registry order, otherwise
  sequential-first-agreed.
- ``random_shuffle`` — shuffle for load spreading, sequential-first-agreed.
- ``priceless_last`` — priced cheapest first, priceless after.

Forward compatibility: returning ``tuple | None`` rather than a list
means today's single-settlement orchestrator can consume the result as
is. When multi-buy lands (plural ``BuyResult`` + plural settlement),
widen this return to ``list[tuple]`` — four built-ins to port, no
deeper structural change.

Failure semantics: ``negotiate`` propagates exceptions. The policy
decides whether to swallow them (see ``gather_outcomes`` helper) or
fail the whole buy. Surfaces all state instead of pre-filtering it.

Registration / discovery:

    @register_aggregation_policy("my_strat")
    async def _my(matches, negotiate):
        ...

Three places ``load_aggregation_policy`` looks, in order:

1. In-process ``_REGISTRY`` (built-ins + anything decorated with
   ``@register_aggregation_policy``).
2. File-based: ``$XDG_CONFIG_HOME/arkhai/aggregation_policies/<name>/policy.py``
   plus any folder added via ``[buyer.aggregation] extra_policy_paths``.
   Each subdir's name becomes the policy name. The file exports
   ``factory(cfg) -> AggregationPolicy``; ``cfg`` is the buyer's full
   TOML config so policies can read per-policy knobs without us baking
   in a fixed schema. Discovery runs once per process on first
   ``load_aggregation_policy()`` call; failures in one folder are
   logged but don't poison its siblings. A file policy with the same
   name as a built-in overwrites it — the local-tuning override UX,
   matching the storefront's behaviour.
3. Python entry points in group ``market_buyer.aggregation_policies``.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import random as _random
from pathlib import Path
from typing import Any, Awaitable, Callable

from .buyer_client import NegotiationOutcome

logger = logging.getLogger(__name__)


NegotiateFn = Callable[[dict[str, Any]], Awaitable[NegotiationOutcome]]
"""Per-candidate negotiation callback. Curried by the orchestrator from
``negotiate_with_seller`` — everything except the candidate itself
(buyer keys, ceiling, duration, max_rounds) is already bound.
Returns a ``NegotiationOutcome``; raises on network/signature failure
so the policy sees the actual error."""

AggregationPolicy = Callable[
    [list[dict[str, Any]], NegotiateFn],
    Awaitable[tuple[dict[str, Any], NegotiationOutcome] | None],
]


_REGISTRY: dict[str, AggregationPolicy] = {}

DEFAULT_POLICY_NAME = "best_price"

_FILE_POLICIES_DISCOVERED = False


def _default_policy_dir() -> Path:
    """Resolve the XDG-flavoured default aggregation-policy directory.

    Honours ``$XDG_CONFIG_HOME`` so it lines up with the rest of the
    buyer config; falls back to ``~/.config/arkhai/aggregation_policies/``
    on hosts that don't set it. Distinct folder from the storefront's
    negotiation ``policies/`` since the two policy types are unrelated
    and folder names map to the registry without disambiguation.
    """
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "arkhai" / "aggregation_policies"


def _load_buyer_config() -> dict[str, Any]:
    """Read the buyer's TOML config — best effort, never raises.

    Returns ``{}`` if the loader isn't importable (no service package
    on path) or the file doesn't exist. The buyer reads config inline
    via ``service.config_loader.load_user_config`` everywhere else;
    this mirrors that pattern instead of building a singleton.
    """
    try:
        from service.config_loader import load_user_config
        return load_user_config() or {}
    except Exception as exc:
        logger.debug("[AGG-POLICY] config load failed (%s); using empty dict", exc)
        return {}


def _resolve_extra_policy_paths(cfg: dict[str, Any]) -> list[str]:
    """Pull extra aggregation-policy directories out of TOML.

    Accepts ``[buyer.aggregation] extra_policy_paths = [".../a", ...]``
    (list) or a single string. Empty / unset → empty list.
    """
    try:
        from service.config_loader import get_dotted
    except Exception:
        return []
    raw = get_dotted(cfg, "buyer.aggregation.extra_policy_paths")
    if raw is None:
        return []
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, list):
        return [str(p).strip() for p in raw if str(p).strip()]
    return []


def _register_file_policy(folder: Path, cfg: dict[str, Any]) -> bool:
    """Load ``folder/policy.py`` and register its ``factory`` under the
    folder name. Returns True on success, False if the folder doesn't
    look like a policy (missing ``policy.py``/``factory``, or factory
    didn't return a callable). Failures are logged at WARNING; the
    caller continues with siblings.
    """
    policy_file = folder / "policy.py"
    if not policy_file.is_file():
        return False

    name = folder.name
    module_id = f"market_buyer._file_aggregation_policies.{name}"
    try:
        spec = importlib.util.spec_from_file_location(module_id, policy_file)
        if spec is None or spec.loader is None:
            logger.warning("[AGG-POLICY] couldn't build spec for %s", policy_file)
            return False
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as exc:
        logger.warning(
            "[AGG-POLICY] failed to import file policy %s from %s: %s",
            name, policy_file, exc,
        )
        return False

    factory = getattr(module, "factory", None)
    if not callable(factory):
        logger.warning(
            "[AGG-POLICY] %s has no callable 'factory' — skipping",
            policy_file,
        )
        return False

    try:
        policy = factory(cfg)
    except Exception as exc:
        logger.warning(
            "[AGG-POLICY] factory() raised in %s: %s",
            policy_file, exc,
        )
        return False

    if not callable(policy):
        logger.warning(
            "[AGG-POLICY] factory() in %s did not return a callable — skipping",
            policy_file,
        )
        return False

    _REGISTRY[name] = policy
    logger.info("[AGG-POLICY] registered file policy %r from %s", name, policy_file)
    return True


def _discover_file_policies(force: bool = False) -> None:
    """Scan the default + configured policy directories and register
    each subdirectory as a policy named after the folder.

    Runs at most once per process unless ``force=True`` (used by tests).
    Failures in individual folders are logged but don't block other
    folders. Built-in registrations win on cold start; a file policy
    with the same name overwrites them by design — that's the override
    UX for ad-hoc tuning.
    """
    global _FILE_POLICIES_DISCOVERED
    if _FILE_POLICIES_DISCOVERED and not force:
        return
    _FILE_POLICIES_DISCOVERED = True

    cfg = _load_buyer_config()
    candidates = [_default_policy_dir(), *(Path(p) for p in _resolve_extra_policy_paths(cfg))]

    for root in candidates:
        if not root.is_dir():
            logger.debug("[AGG-POLICY] skipping non-existent policy dir %s", root)
            continue
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name.startswith((".", "_")):
                continue
            _register_file_policy(entry, cfg)


def register_aggregation_policy(
    name: str,
) -> Callable[[AggregationPolicy], AggregationPolicy]:
    """Decorator. Registers a named aggregation policy.

    Names must be unique within a process. Re-registering overwrites —
    useful for tests and for local override of built-ins.
    """
    def _decorator(fn: AggregationPolicy) -> AggregationPolicy:
        _REGISTRY[name] = fn
        return fn
    return _decorator


def load_aggregation_policy(name: str | None) -> AggregationPolicy:
    """Resolve a policy by name. ``None`` returns the default.

    Triggers a one-shot scan of file-based policies on first call (see
    ``_discover_file_policies``). Lookup order: in-process registry →
    Python entry points in group ``market_buyer.aggregation_policies``.
    File policies are registered into the in-process registry by the
    scan, so they're found at step 1.
    """
    _discover_file_policies()

    if not name:
        name = DEFAULT_POLICY_NAME
    if name in _REGISTRY:
        return _REGISTRY[name]

    try:
        import importlib.metadata as md
        eps = md.entry_points(group="market_buyer.aggregation_policies")
    except Exception:
        eps = []
    for ep in eps:
        if ep.name == name:
            loaded = ep.load()
            _REGISTRY[name] = loaded
            return loaded

    raise ValueError(
        f"Unknown across-seller aggregation policy: {name!r}. "
        f"Registered: {sorted(_REGISTRY)}"
    )


def list_aggregation_policies() -> list[str]:
    """Names of all registered policies (for CLI help / introspection)."""
    return sorted(_REGISTRY)


# ---------------------------------------------------------------------------
# Helpers for policy authors
# ---------------------------------------------------------------------------


async def gather_outcomes(
    negotiate: NegotiateFn,
    candidates: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], NegotiationOutcome | BaseException]]:
    """Run ``negotiate`` against every candidate concurrently.

    Each task's exception is captured in the result tuple rather than
    propagated — the policy can then filter / inspect / re-raise as it
    chooses. The orchestrator never silently swallows; this helper is
    opt-in for policies that explicitly want resilient comparison.
    """
    async def _one(
        c: dict[str, Any],
    ) -> tuple[dict[str, Any], NegotiationOutcome | BaseException]:
        try:
            return (c, await negotiate(c))
        except BaseException as exc:  # noqa: BLE001 — policy-author convenience
            return (c, exc)

    return await asyncio.gather(*(_one(c) for c in candidates))


def _extract_advertised_price(match: dict[str, Any]) -> int | None:
    """Pull the per-hour advertised price from a match's first accepted escrow.

    Mirrors what the seller advertises: ``accepted_escrows[0].price_per_hour``
    (or 0 for free / None for hidden reserve). Returns ``None`` if no usable
    rate is published — callers fall back to their own ``initial_price``.
    """
    accepted = match.get("accepted_escrows") or []
    if isinstance(accepted, str):
        try:
            accepted = json.loads(accepted)
        except (ValueError, TypeError):
            return None
    if not isinstance(accepted, list) or not accepted:
        return None
    first = accepted[0]
    if not isinstance(first, dict):
        return None
    amount = first.get("price_per_hour")
    try:
        parsed = int(amount) if amount is not None else None
    except (ValueError, TypeError):
        return None
    if parsed is None or parsed <= 0:
        return None
    return parsed


async def _sequential_first_agreed(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
) -> tuple[dict[str, Any], NegotiationOutcome] | None:
    """Walk candidates in order; first ``status=="agreed"`` wins."""
    for c in candidates:
        outcome = await negotiate(c)
        if outcome.status == "agreed" and outcome.agreed_price is not None:
            return (c, outcome)
    return None


# ---------------------------------------------------------------------------
# Built-in policies
# ---------------------------------------------------------------------------


@register_aggregation_policy("cheapest_first")
async def _cheapest_first(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
) -> tuple[dict[str, Any], NegotiationOutcome] | None:
    """Sort by advertised price ascending, negotiate sequentially, first agreed wins.

    Priceless listings sort to the end. Same effective behavior as the
    pre-callback loop default — preserves backward compatibility.
    """
    def _key(m: dict[str, Any]) -> tuple[int, int]:
        price = _extract_advertised_price(m)
        if price is None:
            return (1, 0)
        return (0, price)

    return await _sequential_first_agreed(sorted(candidates, key=_key), negotiate)


@register_aggregation_policy("registry_order")
async def _registry_order(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
) -> tuple[dict[str, Any], NegotiationOutcome] | None:
    """No-op order: take registry's response order, first agreed wins."""
    return await _sequential_first_agreed(list(candidates), negotiate)


@register_aggregation_policy("random_shuffle")
async def _random_shuffle(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
) -> tuple[dict[str, Any], NegotiationOutcome] | None:
    """Uniform shuffle for load spreading. First agreed wins."""
    shuffled = list(candidates)
    _random.shuffle(shuffled)
    return await _sequential_first_agreed(shuffled, negotiate)


@register_aggregation_policy("priceless_last")
async def _priceless_last(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
) -> tuple[dict[str, Any], NegotiationOutcome] | None:
    """Priced cheapest first, then priceless. Sequential-first-agreed."""
    priced: list[tuple[int, int, dict[str, Any]]] = []
    priceless: list[tuple[int, dict[str, Any]]] = []
    for idx, m in enumerate(candidates):
        p = _extract_advertised_price(m)
        if p is None:
            priceless.append((idx, m))
        else:
            priced.append((p, idx, m))
    priced.sort(key=lambda t: (t[0], t[1]))
    priceless.sort(key=lambda t: t[0])
    ordered = [m for _, _, m in priced] + [m for _, m in priceless]
    return await _sequential_first_agreed(ordered, negotiate)


def _resolve_best_price_timeout() -> float | None:
    """Optional wall-clock budget for ``best_price`` (seconds).

    Read from ``[buyer.aggregation] best_price_timeout`` in TOML. Unset,
    non-numeric, or non-positive → no timeout (the policy waits for
    every candidate). A positive value caps the comparison at the
    given number of seconds; any candidate still negotiating when the
    timeout fires is cancelled and excluded from the winner pool.
    """
    cfg = _load_buyer_config()
    try:
        from service.config_loader import get_dotted
    except Exception:
        return None
    raw = get_dotted(cfg, "buyer.aggregation.best_price_timeout")
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _pick_min_agreed(
    results: list[tuple[dict[str, Any], NegotiationOutcome | BaseException]],
) -> tuple[dict[str, Any], NegotiationOutcome] | None:
    """Pick the candidate with the lowest agreed_price from a result set."""
    agreed: list[tuple[dict[str, Any], NegotiationOutcome]] = []
    for c, r in results:
        if (
            isinstance(r, NegotiationOutcome)
            and r.status == "agreed"
            and r.agreed_price is not None
        ):
            agreed.append((c, r))
    if not agreed:
        return None
    return min(agreed, key=lambda p: p[1].agreed_price or 0)


@register_aggregation_policy("best_price")
async def _best_price(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
) -> tuple[dict[str, Any], NegotiationOutcome] | None:
    """Negotiate with every candidate in parallel; pick the lowest agreed price.

    The canonical "comparison shopping" example. Bound the candidate
    list upstream (``max_matches_to_try``) to control fan-out;
    optionally cap wall time with ``[buyer.aggregation] best_price_timeout``
    so one slow seller can't hold up the whole buy.

    Without a timeout, costs N negotiations of wall time at most. With
    a timeout, returns the best of whoever completed by the deadline;
    pending negotiations are cancelled and their outcomes discarded.
    Per-candidate failures (network, signature) are skipped, not
    raised — if you want failures to abort the buy, write a policy
    that doesn't use ``gather_outcomes``.
    """
    timeout = _resolve_best_price_timeout()
    if timeout is None:
        return _pick_min_agreed(await gather_outcomes(negotiate, candidates))

    async def _one(
        c: dict[str, Any],
    ) -> tuple[dict[str, Any], NegotiationOutcome | BaseException]:
        try:
            return (c, await negotiate(c))
        except BaseException as exc:  # noqa: BLE001 — comparison swallows per-task
            return (c, exc)

    tasks = [asyncio.create_task(_one(c)) for c in candidates]
    try:
        done, _pending = await asyncio.wait(
            tasks, timeout=timeout, return_when=asyncio.ALL_COMPLETED,
        )
        if len(done) < len(tasks):
            logger.info(
                "[AGG-POLICY] best_price timeout fired at %.2fs; "
                "settling on %d/%d completed candidates",
                timeout, len(done), len(tasks),
            )
        return _pick_min_agreed([t.result() for t in done])
    finally:
        pending_now = [t for t in tasks if not t.done()]
        for t in pending_now:
            t.cancel()
        if pending_now:
            # Drain so cancellation propagates and we don't leak
            # warnings about un-awaited tasks at shutdown.
            await asyncio.gather(*pending_now, return_exceptions=True)


@register_aggregation_policy("fastest_agreed")
async def _fastest_agreed(
    candidates: list[dict[str, Any]],
    negotiate: NegotiateFn,
) -> tuple[dict[str, Any], NegotiationOutcome] | None:
    """Race N parallel negotiations; take whichever agrees first.

    For "provision ASAP, price-insensitive" buys. Sellers that exit or
    raise are dropped and the race continues against the survivors;
    once a winner is found, the remaining in-flight tasks are
    cancelled. Returns None if nobody ever agrees.

    Note on cancellation: cancelling a task that's mid-``negotiate``
    surfaces a ``CancelledError`` inside the underlying HTTP call; in
    practice the buyer's request is dropped without writing anything,
    and the seller's side may briefly hold an open thread that the
    server-side watchdog reaps. Acceptable for the fast-buy use case
    this policy exists for.
    """
    if not candidates:
        return None

    async def _one(
        c: dict[str, Any],
    ) -> tuple[dict[str, Any], NegotiationOutcome | BaseException]:
        try:
            return (c, await negotiate(c))
        except BaseException as exc:  # noqa: BLE001 — exceptions belong to the race
            return (c, exc)

    pending: set[asyncio.Task[Any]] = {asyncio.create_task(_one(c)) for c in candidates}
    try:
        while pending:
            done, pending = await asyncio.wait(
                pending, return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                c, outcome = task.result()
                if (
                    isinstance(outcome, NegotiationOutcome)
                    and outcome.status == "agreed"
                    and outcome.agreed_price is not None
                ):
                    return (c, outcome)
        return None
    finally:
        for t in pending:
            t.cancel()
        if pending:
            # Drain so cancellation propagates and we don't leak warnings
            # about un-awaited tasks at interpreter shutdown.
            await asyncio.gather(*pending, return_exceptions=True)
