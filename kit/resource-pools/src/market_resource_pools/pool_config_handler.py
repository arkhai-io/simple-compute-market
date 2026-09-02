"""Provider-specific resource-pool configuration boundary.

Implementations validate and persist the configuration associated with one
resource-pool provider.  The caller owns the unit of work: handlers must not
commit or roll back transactions themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, TypeVar

UnitOfWorkT = TypeVar("UnitOfWorkT")


@dataclass(frozen=True)
class PoolConfigValidationProblem:
    """One provider-specific configuration problem, relative to provider_config."""

    path: str
    code: str
    message: str


class PoolConfigHandler(Protocol[UnitOfWorkT]):
    """Validate and persist one provider's pool configuration.

    Reads come at two levels of disclosure. ``read_config`` omits every secret
    a provider holds and is what serves API responses, the export document,
    administrative round-trips, and reconciliation comparison.
    ``read_config_for_execution`` may decrypt secrets and resolve references,
    and is reserved for preparing provider input at dispatch.

    The unqualified name belongs to the read that omits secrets deliberately.
    A caller that forgets to ask for them loses a value it needed and fails on
    the execution path, which is loud; the reverse mistake would place a
    credential in a serialized response, which is silent.
    """

    provider: str

    def validate_config(self, config: Mapping[str, Any]) -> dict[str, Any]: ...

    def validate_config_problems(
        self, config: Mapping[str, Any]
    ) -> tuple[dict[str, Any] | None, tuple[PoolConfigValidationProblem, ...]]: ...

    def read_config(
        self, unit_of_work: UnitOfWorkT, pool_id: str
    ) -> dict[str, Any]: ...

    def read_config_for_execution(
        self, unit_of_work: UnitOfWorkT, pool_id: str
    ) -> dict[str, Any]: ...

    def replace_config(
        self,
        unit_of_work: UnitOfWorkT,
        pool_id: str,
        config: Mapping[str, Any],
    ) -> None: ...

    def delete_config(self, unit_of_work: UnitOfWorkT, pool_id: str) -> None: ...
