"""What a storefront hands the selling library: one frozen bundle of its domain's contributions.

The library discovers or imports no domain.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from arkhai_api.issuance import IssuanceResult
from arkhai_api.labels import IssuanceLabel
from market_negotiation_runtime import Acceptance
from pydantic import BaseModel

_KIND = re.compile(r"^([a-z][a-z0-9_]*)\.v1$")
_TABLE_PREFIX = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class IssuanceSubject:
    """What a listing sells, as the authority's issuance command names it.

    ``endpoint`` is delivery metadata returned beside the key and never digested.
    """

    service: str
    resource_id: str | None
    endpoint: str | None = None


@dataclass(frozen=True)
class QuotaSource:
    """The trusted quota resource a listing is created over."""

    site_id: str
    resource_id: str
    offering_mode: str


IssuanceProjection = Callable[[Mapping[str, Any]], IssuanceSubject]
"""Maps a listing's ``listing_resource`` to its issuance subject."""

PublicationMapping = Callable[[Mapping[str, Any], QuotaSource], Mapping[str, Any]]
"""Maps an operator's publication request and its quota source to a ``listing_resource``."""

PublicationGuard = Callable[[Mapping[str, Any]], str | None]
"""Returns why a ``listing_resource`` may not be published, or ``None``."""

AcceptanceHook = Callable[[Any, Acceptance], Awaitable[None]]
"""Runs with the storefront's repository before an acceptance is recorded."""

PublicResultExtension = Callable[[Mapping[str, Any], IssuanceResult], Mapping[str, Any]]
"""Public fields a delivery carries beside its connection payload; never the secret."""


class ConsumptionRule(enum.Enum):
    """How the domain's gate charges an admitted request."""

    FIXED_PER_REQUEST = "fixed_per_request"


@dataclass(frozen=True)
class SellingContributions:
    """One domain's contributions to the selling library.

    ``kind`` is ``<schema>.v1``, from whose stem the envelope kinds are spelled;
    ``table_prefix`` names the domain's tables and its credentials reference.
    """

    label: IssuanceLabel
    kind: str
    offering_mode: str
    contribution_id: str
    table_prefix: str
    listing_schema: type[BaseModel]
    publication_mapping: PublicationMapping
    issuance_projection: IssuanceProjection
    consumption_rule: ConsumptionRule
    publication_guards: tuple[PublicationGuard, ...] = ()
    acceptance_hook: AcceptanceHook | None = None
    public_result_extension: PublicResultExtension | None = None

    def __post_init__(self) -> None:
        if not _KIND.fullmatch(self.kind):
            raise ValueError("kind must be a lowercase schema name followed by '.v1'")
        if not _TABLE_PREFIX.fullmatch(self.table_prefix):
            raise ValueError("table_prefix must be a lowercase SQL identifier")
        if not self.offering_mode.strip() or not self.contribution_id.strip():
            raise ValueError("offering_mode and contribution_id must be non-empty")
        if "listing_resource" not in self.listing_schema.model_fields:
            raise ValueError("listing_schema must carry a listing_resource field")

    @property
    def schema_name(self) -> str:
        match = _KIND.fullmatch(self.kind)
        assert match is not None
        return match.group(1)

    @property
    def settlement_evidence_kind(self) -> str:
        return f"{self.schema_name}.settlement-evidence.v1"

    @property
    def listing_source_kind(self) -> str:
        return f"{self.schema_name}.quota-listing.v1"

    @property
    def credentials_ref_prefix(self) -> str:
        return f"{self.table_prefix.replace('_', '-')}-credential.v1"

    def table(self, name: str) -> str:
        return f"{self.table_prefix}_{name}"
