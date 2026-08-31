"""Pool configuration for the bare-metal Ansible fulfillment provider."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from market_resource_pools import PoolConfigValidationProblem


class BareMetalPoolConfigHandler:
    """Validate the intentionally configuration-free bare-metal provider.

    Bare-metal execution is selected by the pool's offering mode and uses the
    recorded host/executor identities. Playbook paths and credentials remain
    service configuration rather than buyer-visible or pool-local overrides.
    """

    provider = "bare_metal.ansible"

    def validate_config(self, config: Mapping[str, Any]) -> dict[str, Any]:
        normalized, problems = self.validate_config_problems(config)
        if problems:
            raise ValueError(problems[0].message)
        assert normalized is not None
        return normalized

    def validate_config_problems(
        self, config: Mapping[str, Any]
    ) -> tuple[dict[str, Any] | None, tuple[PoolConfigValidationProblem, ...]]:
        if not isinstance(config, Mapping):
            return None, (
                PoolConfigValidationProblem(
                    path="",
                    code="invalid_type",
                    message="bare-metal provider configuration must be an object",
                ),
            )
        if config:
            return None, tuple(
                PoolConfigValidationProblem(
                    path=str(key),
                    code="unknown_field",
                    message=(
                        "bare-metal provider configuration does not accept "
                        f"pool-local field {key!r}"
                    ),
                )
                for key in sorted(config)
            )
        return {}, ()

    def read_config(self, unit_of_work: Any, pool_id: str) -> dict[str, Any]:
        del unit_of_work, pool_id
        return {}

    def replace_config(
        self,
        unit_of_work: Any,
        pool_id: str,
        config: Mapping[str, Any],
    ) -> None:
        del unit_of_work, pool_id
        self.validate_config(config)

    def delete_config(self, unit_of_work: Any, pool_id: str) -> None:
        del unit_of_work, pool_id
