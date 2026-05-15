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

URL sugar (single-value query params) maps to the set form via the
filter's ``alias_kind``:

* default — ``?gpu_model=H100`` → ``in: ["H100"]``
* ``lower_bound`` — ``?ram_gb_min=16`` → ``range: {min: 16, min_inclusive: true}``
* ``upper_bound`` — ``?ram_gb_max=128`` → ``range: {max: 128, max_inclusive: true}``

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


def _build_in_criterion(decl: FilterDecl, raw: str) -> Criterion:
    coerced = _coerce_scalar(raw, decl.value_type, decl.name)
    return Criterion(
        name=decl.name,
        path_expr=_get_parsed_path(decl.path),
        on_missing=decl.on_missing,
        op="in",
        values=(coerced,),
    )


def _build_range_criterion(decl: FilterDecl, raw: str) -> Criterion:
    coerced = _coerce_scalar(raw, decl.value_type, decl.name)
    if decl.alias_kind == "lower_bound":
        rng = _Range(min=coerced, max=None, min_inclusive=True, max_inclusive=True)
    elif decl.alias_kind == "upper_bound":
        rng = _Range(min=None, max=coerced, min_inclusive=True, max_inclusive=True)
    else:
        raise FilterParamError(
            f"{decl.name}: range filter with no alias_kind can't be expressed "
            f"as a single-value URL param (raw set-form is an (a2) feature)"
        )
    return Criterion(
        name=decl.name,
        path_expr=_get_parsed_path(decl.path),
        on_missing=decl.on_missing,
        op="range",
        range_=rng,
    )


def build_criteria(
    spec: FilterSpec, query_params: dict[str, str]
) -> list[Criterion]:
    """Translate raw URL params into a list of evaluable criteria.

    Unknown filter names raise ``FilterParamError`` (→ 400).  Empty
    values are skipped (FastAPI may pass empty strings through).
    """
    by_name = {f.name: f for f in spec.filters}
    out: list[Criterion] = []
    for name, raw in query_params.items():
        if raw is None or raw == "":
            continue
        decl = by_name.get(name)
        if decl is None:
            raise FilterParamError(f"unknown filter: {name!r}")
        if decl.op == "in":
            out.append(_build_in_criterion(decl, raw))
        elif decl.op == "range":
            out.append(_build_range_criterion(decl, raw))
        elif decl.op == "not_in":
            coerced = _coerce_scalar(raw, decl.value_type, decl.name)
            out.append(Criterion(
                name=decl.name,
                path_expr=_get_parsed_path(decl.path),
                on_missing=decl.on_missing,
                op="not_in",
                values=(coerced,),
            ))
        elif decl.op == "exists":
            wants = _coerce_scalar(raw, "boolean", decl.name)
            out.append(Criterion(
                name=decl.name,
                path_expr=_get_parsed_path(decl.path),
                on_missing=decl.on_missing,
                op="exists",
                exists_target=wants,
            ))
        else:
            raise FilterParamError(
                f"{decl.name}: unsupported op {decl.op!r}"
            )
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
    return [m.value for m in crit.path_expr.find(listing)]


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
