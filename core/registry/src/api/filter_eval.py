"""Filter evaluator for GET /listings.

Drives off the registry's filter-spec — every accepted query-param name
is a declared filter, every filter is `(path, op, value_type, on_missing,
alias_kind?)`.  The evaluator is generic over the spec: drop a new filter
in YAML, ?new_filter=... works without code changes.

Set-theoretic op model (closed set):

* ``in: [v1, v2, ...]`` — passes iff path-resolution ∩ values ≠ ∅
* ``not_in: [v1, ...]`` — passes iff path-resolution ∩ values = ∅
* ``range: {min, max, min_inclusive, max_inclusive}`` — passes iff
  at least one resolved value falls inside the interval
* ``exists: bool`` — does the path resolve to anything

Array projections in the path (``$.foo[*].bar``) get array-projection
semantics for free: "at least one element matches."  Scalar paths
collapse to a singleton resolution set.

Two URL surfaces, both honoured per request:

* **URL sugar** (single-value query params) maps to the set form via
  the filter's ``alias_kind``:

  - default — ``?gpu_model=H100`` → ``in: ["H100"]``
  - ``lower_bound`` — ``?ram_gb_min=16`` → ``range: {min: 16, min_inclusive: true}``
  - ``upper_bound`` — ``?ram_gb_max=128`` → ``range: {max: 128, max_inclusive: true}``

* **Raw set-form** (any filter's declared op):

  - ``?gpu_model=in:[H100,A100]`` — in-set with multiple values
  - ``?region=not_in:[California,Texas]`` — set complement (requires
    the spec to declare the filter as ``op: not_in``)
  - ``?ram_gb_min=range:[16,128]`` — bounded interval, square brackets
    are inclusive, parens are exclusive (e.g. ``(16,)`` = strictly >16,
    unbounded above; ``[,128]`` = no lower bound, ≤128)
  - ``?has_oracle=exists:true`` — presence/absence test

  Raw set-form is triggered when the value starts with ``<op>:`` and the
  payload syntax matches. The op must equal the filter's declared op —
  set-form is a richer encoding of the same op, not an op selector.

**Per-query ``on_missing`` override.** A query may pass
``?strict.<filter>=true`` to flip the filter's spec-level ``on_missing``
to ``fail`` for this one request; ``?strict.<filter>=false`` flips it
to ``pass``. Useful for buyers that want to tighten an underreport-
friendly default (``token`` defaults to ``on_missing: pass`` so sellers
who advertise no escrows still show up — strict mode rejects them).

This module is deliberately stateless: it takes a listing dict + a
``Criterion`` and returns a bool.  Caching of parsed JSONPaths lives at
the spec-loader edge (one parse per filter at startup).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from jsonpath_ng.ext import parse as _jsonpath_parse

from src.api.filter_spec import FilterDecl, FilterSpec


# ---------------------------------------------------------------------------
# Parsed-criterion model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Range:
    min: float | int | None
    max: float | int | None
    min_inclusive: bool
    max_inclusive: bool

    def contains(self, x: float | int) -> bool:
        if self.min is not None:
            if x < self.min:
                return False
            if x == self.min and not self.min_inclusive:
                return False
        if self.max is not None:
            if x > self.max:
                return False
            if x == self.max and not self.max_inclusive:
                return False
        return True


@dataclass(frozen=True)
class Criterion:
    """One parsed filter constraint, ready to evaluate against a listing."""

    name: str
    path_expr: Any  # parsed jsonpath-ng expression
    on_missing: str  # "fail" | "pass"
    op: str         # "in" | "not_in" | "range" | "exists"
    values: tuple[Any, ...] | None = None  # for in / not_in
    range_: _Range | None = None
    exists_target: bool | None = None


class FilterParamError(ValueError):
    """Raised when a query param can't be coerced or violates the spec.

    The HTTP layer surfaces these as 400 with the message.
    """


# ---------------------------------------------------------------------------
# Value coercion (string-from-URL → typed value the path resolves to)
# ---------------------------------------------------------------------------


def _coerce_scalar(raw: str, value_type: str, filter_name: str) -> Any:
    if value_type == "string" or value_type == "address":
        return raw
    if value_type == "integer":
        try:
            return int(raw)
        except ValueError as exc:
            raise FilterParamError(
                f"{filter_name}: expected integer, got {raw!r}"
            ) from exc
    if value_type == "number":
        try:
            return float(raw)
        except ValueError as exc:
            raise FilterParamError(
                f"{filter_name}: expected number, got {raw!r}"
            ) from exc
    if value_type == "boolean":
        if raw.lower() in ("true", "1", "yes"):
            return True
        if raw.lower() in ("false", "0", "no"):
            return False
        raise FilterParamError(
            f"{filter_name}: expected boolean, got {raw!r}"
        )
    raise FilterParamError(
        f"{filter_name}: unsupported value_type {value_type!r}"
    )


# ---------------------------------------------------------------------------
# Building criteria from URL params
# ---------------------------------------------------------------------------


_STRICT_PREFIX = "strict."


def _try_set_form(raw: str) -> tuple[str, str] | None:
    """Recognize ``<op>:<payload>`` set-form, return (op, payload) or None.

    Only succeeds when the payload syntax matches the op:
    * ``in:`` / ``not_in:`` — payload must start with ``[``
    * ``range:`` — payload must start with ``[`` or ``(``
    * ``exists:`` — payload must be a boolean literal (true/false/1/0/yes/no)

    Anything else falls through to the URL-sugar path. This lets a
    string-valued filter like ``?gpu_model=in:thing`` still parse as the
    literal string ``in:thing`` rather than a malformed set-form.
    """
    # Check longest prefixes first to avoid "in:" matching inside "not_in:".
    for op in ("not_in", "range", "exists", "in"):
        prefix = op + ":"
        if not raw.startswith(prefix):
            continue
        payload = raw[len(prefix):]
        if op in ("in", "not_in") and payload.startswith("["):
            return op, payload
        if op == "range" and (payload.startswith("[") or payload.startswith("(")):
            return op, payload
        if op == "exists" and payload.lower() in ("true", "false", "1", "0", "yes", "no"):
            return op, payload
        # Recognized op prefix but malformed payload — fall through; the
        # URL-sugar branch will likely error in a way the user can read.
    return None


def _parse_value_list(payload: str, value_type: str, filter_name: str) -> tuple[Any, ...]:
    """Parse ``[v1,v2,...]`` into a tuple of coerced values.

    Empty list (``[]``) is allowed and yields ``()`` — matches nothing
    for ``in``, matches everything for ``not_in``. Whitespace around
    items is stripped before coercion.
    """
    s = payload.strip()
    if not (s.startswith("[") and s.endswith("]")):
        raise FilterParamError(
            f"{filter_name}: set form must be enclosed in '[ ]' — got {payload!r}"
        )
    inner = s[1:-1].strip()
    if not inner:
        return ()
    raw_items = [item.strip() for item in inner.split(",")]
    return tuple(_coerce_scalar(item, value_type, filter_name) for item in raw_items)


def _parse_interval(payload: str, value_type: str, filter_name: str) -> _Range:
    """Parse interval notation into a ``_Range``.

    Syntax: ``[min,max]`` for closed, ``(min,max)`` for open, mix-and-
    match for half-open. Empty endpoints mean unbounded (e.g. ``[16,)``
    is "≥16, no upper bound"; ``(,128]`` is "no lower bound, ≤128").
    Numeric value types only — string ranges don't make sense.
    """
    s = payload.strip()
    if not s or s[0] not in "[(" or s[-1] not in "])":
        raise FilterParamError(
            f"{filter_name}: range form requires '[ ]' or '( )' delimiters — got {payload!r}"
        )
    min_inclusive = s[0] == "["
    max_inclusive = s[-1] == "]"
    inner = s[1:-1]
    if "," not in inner:
        raise FilterParamError(
            f"{filter_name}: range form needs a ',' separator — e.g. [16,128] or [16,)"
        )
    min_raw, max_raw = inner.split(",", 1)
    min_raw, max_raw = min_raw.strip(), max_raw.strip()
    lo = _coerce_scalar(min_raw, value_type, filter_name) if min_raw else None
    hi = _coerce_scalar(max_raw, value_type, filter_name) if max_raw else None
    if lo is None and hi is None:
        raise FilterParamError(f"{filter_name}: range needs at least one bound")
    return _Range(min=lo, max=hi, min_inclusive=min_inclusive, max_inclusive=max_inclusive)


def _build_criterion(
    decl: FilterDecl,
    raw: str,
    on_missing: str,
) -> Criterion:
    """Build one criterion for a known filter, choosing set-form or URL-sugar."""
    parsed = _get_parsed_path(decl.path)
    set_form = _try_set_form(raw)

    if set_form is not None:
        op_token, payload = set_form
        if op_token != decl.op:
            raise FilterParamError(
                f"{decl.name}: filter declares op={decl.op!r}, "
                f"URL uses op={op_token!r}"
            )
        if op_token in ("in", "not_in"):
            values = _parse_value_list(payload, decl.value_type, decl.name)
            return Criterion(
                name=decl.name, path_expr=parsed, on_missing=on_missing,
                op=op_token, values=values,
            )
        if op_token == "range":
            rng = _parse_interval(payload, decl.value_type, decl.name)
            return Criterion(
                name=decl.name, path_expr=parsed, on_missing=on_missing,
                op="range", range_=rng,
            )
        if op_token == "exists":
            wants = _coerce_scalar(payload, "boolean", decl.name)
            return Criterion(
                name=decl.name, path_expr=parsed, on_missing=on_missing,
                op="exists", exists_target=wants,
            )

    # URL-sugar fallback — only valid for filters with a single-value
    # surface (in / range with alias_kind).  not_in / exists must use
    # raw set-form on the wire; reject single-value usage with a hint.
    if decl.op == "in":
        coerced = _coerce_scalar(raw, decl.value_type, decl.name)
        return Criterion(
            name=decl.name, path_expr=parsed, on_missing=on_missing,
            op="in", values=(coerced,),
        )
    if decl.op == "range":
        coerced = _coerce_scalar(raw, decl.value_type, decl.name)
        if decl.alias_kind == "lower_bound":
            rng = _Range(min=coerced, max=None, min_inclusive=True, max_inclusive=True)
        elif decl.alias_kind == "upper_bound":
            rng = _Range(min=None, max=coerced, min_inclusive=True, max_inclusive=True)
        else:
            raise FilterParamError(
                f"{decl.name}: range filter with no alias_kind needs raw set-form "
                f"(e.g. range:[16,128]) — single-value URL form has no bound semantics"
            )
        return Criterion(
            name=decl.name, path_expr=parsed, on_missing=on_missing,
            op="range", range_=rng,
        )
    if decl.op in ("not_in", "exists"):
        raise FilterParamError(
            f"{decl.name}: {decl.op} filter must be invoked via set-form "
            f"(e.g. {decl.op}:[...] / exists:true) — single-value URL form is ambiguous"
        )
    raise FilterParamError(f"{decl.name}: unsupported op {decl.op!r}")


def _extract_strict_overrides(
    by_name: dict[str, FilterDecl],
    query_params: dict[str, str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Split query_params into (real_filters, strict_overrides).

    Strict overrides map filter name → "fail" | "pass" and replace the
    spec-level ``on_missing`` for that filter on this request. An
    override targeting a filter not declared in the spec is a typo and
    raises 400 — even though the filter may not be used in this
    particular query, silent acceptance would let mistakes slide.
    """
    overrides: dict[str, str] = {}
    real: dict[str, str] = {}
    for k, v in query_params.items():
        if not k.startswith(_STRICT_PREFIX):
            real[k] = v
            continue
        target = k[len(_STRICT_PREFIX):]
        if not target:
            raise FilterParamError("strict.: missing filter name")
        if target not in by_name:
            raise FilterParamError(f"strict.{target}: unknown filter")
        wants_strict = _coerce_scalar(v, "boolean", k)
        overrides[target] = "fail" if wants_strict else "pass"
    return real, overrides


def build_criteria(
    spec: FilterSpec, query_params: dict[str, str]
) -> list[Criterion]:
    """Translate raw URL params into a list of evaluable criteria.

    Unknown filter names raise ``FilterParamError`` (→ 400). Empty
    values are skipped (FastAPI may pass empty strings through).
    ``strict.<name>`` keys are consumed as per-request ``on_missing``
    overrides; targets must reference a declared filter.
    """
    by_name = {f.name: f for f in spec.filters}
    real_params, overrides = _extract_strict_overrides(by_name, query_params)

    out: list[Criterion] = []
    for name, raw in real_params.items():
        if raw is None or raw == "":
            continue
        decl = by_name.get(name)
        if decl is None:
            raise FilterParamError(f"unknown filter: {name!r}")
        on_missing = overrides.get(name, decl.on_missing)
        out.append(_build_criterion(decl, raw, on_missing))
    return out


# ---------------------------------------------------------------------------
# Path parsing — cached per (filter_name, path) pair
# ---------------------------------------------------------------------------


@lru_cache(maxsize=128)
def _get_parsed_path(path: str) -> Any:
    return _jsonpath_parse(path)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _resolve(listing: dict[str, Any], crit: Criterion) -> list[Any]:
    """Resolve the criterion's path, dropping JSON-null matches.

    Treating ``null`` as absent makes every op consistent with what a
    buyer expects: ``in:[X]`` against ``gpu_model: null`` doesn't match
    (because you can't write the value ``null`` in a URL); ``exists:true``
    against ``oracle_address: null`` is false, not true (the column is
    present but carries no value); ``not_in:[X]`` against a null value
    falls into ``on_missing`` rather than vacuously passing.
    """
    return [m.value for m in crit.path_expr.find(listing) if m.value is not None]


def evaluate(listing: dict[str, Any], crit: Criterion) -> bool:
    """Apply one criterion to one listing dict, return pass/fail.

    Resolution semantics: empty path-resolution → on_missing decides
    (fail = reject, pass = ignore-this-criterion).
    """
    resolved = _resolve(listing, crit)

    if not resolved:
        return crit.on_missing == "pass"

    if crit.op == "in":
        # passes iff at least one resolved value matches any set member
        sset = set(crit.values or ())
        return any(v in sset for v in resolved)

    if crit.op == "not_in":
        sset = set(crit.values or ())
        return all(v not in sset for v in resolved)

    if crit.op == "range":
        rng = crit.range_
        assert rng is not None
        return any(rng.contains(v) for v in resolved if isinstance(v, (int, float)))

    if crit.op == "exists":
        # resolved is non-empty here (handled above); empty case handled above
        return crit.exists_target is True

    raise FilterParamError(f"unknown op {crit.op!r}")


def evaluate_all(listing: dict[str, Any], criteria: list[Criterion]) -> bool:
    """Listing passes iff every criterion passes (AND semantics)."""
    return all(evaluate(listing, c) for c in criteria)
