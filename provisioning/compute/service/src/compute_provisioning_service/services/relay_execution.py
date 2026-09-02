"""Resolving a relay's address and admission token at execution.

An accepted operation carries the relay *reference* and the leased remote port,
never the token. The address and token are read here, immediately before a
job's variables are written.

Two independent reasons, either sufficient on its own.

The accepted operation's parameters are persisted unencrypted in a JSON column
and returned by the job endpoints. A token placed among them is neither
protected at rest nor withheld from a read, which is the whole of what this
system claims about relay credentials.

And a token rotated through the relay controller has to take effect on the next
execution, including a retry of a job accepted before the rotation. A snapshot
pins the value that was correct at acceptance, which after a rotation is
precisely the value that no longer works.

This is a deliberate exception to the rule that an accepted operation snapshots
its resolved provider variables. The rule exists so an operator editing pool
configuration cannot change what a running job does; a credential is the one
input where the newest value is the correct one.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from market_config import decrypt_secret

from compute_provisioning_service.db.models import Relay


class RelayUnusableAtExecutionError(RuntimeError):
    """The referenced relay cannot carry a tunnel now.

    Raised as a configuration error rather than a transient one. A retry runs
    against the same configuration and fails identically, so burning the retry
    budget only delays the same outcome behind a misleading `running` state.
    """


class RelayExecutionResolver:
    def __init__(self, session_factory: Any, settings: Any) -> None:
        self._session_factory = session_factory
        self._settings = settings

    def resolve_into(self, params: Any) -> Any:
        """Return *params* with the relay's address and token filled in.

        A job with no relay reference is the direct-NAT path and passes
        through untouched.
        """
        relay_id = getattr(params, "relay_id", None)
        if not relay_id:
            return params

        with self._session_factory() as db:
            relay = db.get(Relay, relay_id)
            if relay is None:
                raise RelayUnusableAtExecutionError(
                    f"job references relay '{relay_id}', which no longer exists; "
                    "the VM would be created with no external route"
                )
            if not relay.enabled:
                raise RelayUnusableAtExecutionError(
                    f"relay '{relay_id}' ({relay.relay_addr}:{relay.relay_port}) "
                    "is disabled, so it will not admit this host's tunnel client"
                )
            if not relay.relay_token_encrypted:
                raise RelayUnusableAtExecutionError(
                    f"relay '{relay_id}' has no admission token configured, so "
                    "the tunnel client would be refused at the rendezvous"
                )
            token = decrypt_secret(
                relay.relay_token_encrypted,
                str(getattr(self._settings, "ssh_decryption_key", "") or ""),
            )
            return replace(
                params,
                relay_addr=relay.relay_addr,
                relay_port=relay.relay_port,
                relay_token=token,
            )
