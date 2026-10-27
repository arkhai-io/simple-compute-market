"""The issuance label: the one name a domain gives the family's digests and evidence."""

from __future__ import annotations

import re
from dataclasses import dataclass

_NAME = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
_FULFILLMENT_ID_PREFIX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


@dataclass(frozen=True)
class IssuanceLabel:
    """A domain's name as every schema string the family digests and signs spells it.

    ``fulfillment_id_prefix`` defaults to ``<name>-fulfillment.v1``; a domain
    whose recorded grants predate the family passes the prefix those grants carry.
    """

    name: str
    fulfillment_id_prefix: str = ""

    def __post_init__(self) -> None:
        if len(self.name) > 64 or not _NAME.fullmatch(self.name):
            raise ValueError("issuance label must be lowercase words joined by hyphens")
        if not self.fulfillment_id_prefix:
            object.__setattr__(self, "fulfillment_id_prefix", f"{self.name}-fulfillment.v1")
        if not _FULFILLMENT_ID_PREFIX.fullmatch(self.fulfillment_id_prefix):
            raise ValueError("fulfillment_id_prefix must be a safe reference without ':'")

    @property
    def issuance_request_schema(self) -> str:
        return f"arkhai.{self.name}.issuance-request.v1"

    @property
    def issuance_result_schema(self) -> str:
        return f"arkhai.{self.name}.issuance-result.v1"

    @property
    def evidence_protocol(self) -> str:
        return f"arkhai.{self.name}.issuance-evidence.v1"

    @property
    def evidence_capability(self) -> str:
        return f"{self.name}.issuance.v1"

    @property
    def portable_fulfillment_ref_schema(self) -> str:
        return f"arkhai.{self.name}.portable-fulfillment-ref.v1"
