"""Provider-specific resource-pool configuration boundary.

Implementations validate and persist the configuration associated with one
resource-pool provider.  The caller owns the unit of work: handlers must not
commit or roll back transactions themselves.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, TypeVar

UnitOfWorkT = TypeVar("UnitOfWorkT")


class PoolConfigHandler(Protocol[UnitOfWorkT]):
    """Validate and persist one provider's pool configuration."""

    provider: str

    def validate_config(self, config: Mapping[str, Any]) -> dict[str, Any]: ...

    def read_config(self, unit_of_work: UnitOfWorkT, pool_id: str) -> dict[str, Any]: ...

    def replace_config(
        self,
        unit_of_work: UnitOfWorkT,
        pool_id: str,
        config: Mapping[str, Any],
    ) -> None: ...

    def delete_config(self, unit_of_work: UnitOfWorkT, pool_id: str) -> None: ...
