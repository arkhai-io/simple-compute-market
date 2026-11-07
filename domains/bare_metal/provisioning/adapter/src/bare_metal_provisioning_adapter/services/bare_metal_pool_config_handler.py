"""Pool configuration for the bare-metal Ansible fulfillment provider."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from compute_provisioning.hosts import ConnectionCodecs
from compute_provisioning.relays import (
    RELAY_ID_FIELD,
    pool_relay_id,
    relay_execution_fields,
    set_pool_relay,
    validate_relay_reference,
)
from market_resource_pools import PoolConfigValidationProblem


class BareMetalPoolConfigHandler:
    """Validate the bare-metal provider's one pool-local field: its relay.

    Bare-metal execution is selected by the pool's offering mode and uses the
    recorded host/executor identities. Playbook paths and credentials remain
    service configuration rather than buyer-visible or pool-local overrides.
    The only field a pool states is ``relay_id``, the relay its hosts dial for
    buyer tunnels, which is the compute family's pool relay reference and is
    read and written through it, so the family's rebinding rule governs it.
    """

    provider = "bare_metal.ansible"

    def __init__(
        self,
        settings: Any | None = None,
        connection_codecs: ConnectionCodecs | None = None,
    ) -> None:
        # Settings carry the key that decrypts a relay's admission token for
        # the execution read, which fails loudly for a relay holding a token
        # when no key is configured rather than resolving one without it.
        self._settings = settings
        # The host authority's codecs, through which pointing the pool at a
        # relay checks its hosts' management routes against that relay.
        self._connection_codecs = connection_codecs

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
        problems = [
            PoolConfigValidationProblem(
                path=str(key),
                code="unknown_field",
                message=(
                    "bare-metal provider configuration does not accept "
                    f"pool-local field {key!r}"
                ),
            )
            for key in sorted(set(config) - {RELAY_ID_FIELD})
        ]
        relay_id, relay_problems = validate_relay_reference(config)
        problems.extend(relay_problems)
        if problems:
            return None, tuple(problems)
        return self._shaped(relay_id), ()

    def read_config(self, db: Any, pool_id: str) -> dict[str, Any]:
        """The pool's relay reference, never the relay behind it."""
        return self._shaped(pool_relay_id(db, pool_id))

    def read_config_for_execution(self, db: Any, pool_id: str) -> dict[str, Any]:
        """The configuration with its relay resolved and its token decrypted,
        reserved for preparing provider input at dispatch."""
        config = self.read_config(db, pool_id)
        config.update(
            relay_execution_fields(db, config.get(RELAY_ID_FIELD), self._encryption_key())
        )
        return config

    def replace_config(
        self,
        db: Any,
        pool_id: str,
        config: Mapping[str, Any],
    ) -> None:
        normalized = self.validate_config(config)
        set_pool_relay(
            db, pool_id, normalized.get(RELAY_ID_FIELD), codecs=self._connection_codecs
        )

    @staticmethod
    def _shaped(relay_id: str | None) -> dict[str, Any]:
        # A pool with no relay states nothing, so its configuration reads as
        # the empty mapping a definitions document writes for it.
        return {} if relay_id is None else {RELAY_ID_FIELD: relay_id}

    def _encryption_key(self) -> str:
        return str(getattr(self._settings, "ssh_decryption_key", "") or "")
