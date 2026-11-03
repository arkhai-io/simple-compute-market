"""Resolving a relay's address, admission token, and grant at execution.

An accepted operation carries the relay *reference* and the leased remote port,
never the token or a grant. The address and token are read here, and a job
that adds a proxy has its grant signed here, immediately before its variables
are written, on every attempt: a grant is signed with the relay's key active
at that moment, so a key activated after a job was accepted signs its grant.

Two independent reasons, either sufficient on its own.

The accepted operation's parameters are persisted unencrypted in a JSON column
and returned by the job endpoints. A token placed among them is neither
protected at rest nor withheld from a read, which is the whole of what this
system claims about relay credentials.

And a token rotated through the relay routes has to take effect on the next
execution, including a retry of a job accepted before the rotation. A snapshot
pins the value that was correct at acceptance, which after a rotation is
precisely the value that no longer works.

This is a deliberate exception to the rule that an accepted operation snapshots
its resolved provider variables. The rule exists so an operator editing pool
configuration cannot change what a running job does; a credential is the one
input where the newest value is the correct one.

The resolver works on a domain's dataclass or frozen Pydantic job parameters with
``relay_id``, ``relay_addr``, ``relay_port``, ``relay_token``, and
``relay_grant`` fields. The domain passes the leased port of a job that adds a
proxy, under whatever name its parameters store it, and the reservation that
holds its lease.
"""

from __future__ import annotations

from dataclasses import is_dataclass, replace
from typing import Any

from market_config import decrypt_secret
from pydantic import BaseModel

from .db import Relay, RelayPortLease
from .grants import sign_grant
from .keys import GrantKey


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

    def resolve_into(
        self,
        params: Any,
        *,
        remote_port: int | None = None,
        owner_id: str | None = None,
    ) -> Any:
        """Return *params* with the relay's address and token filled in.

        ``remote_port`` is the leased port of a job that adds a proxy, and
        ``owner_id`` the reservation whose lease holds it; with them, the grant
        for that lease is signed with the relay's active key and filled in too,
        and the lease records the key that signed it. A job that only removes a
        proxy needs no grant and passes no port.

        A job with no relay reference reaches its buyer without a relay and
        passes through untouched.
        """
        if isinstance(params, type) or (not is_dataclass(params) and not (
            isinstance(params, BaseModel) and params.model_config.get("frozen")
        )):
            raise TypeError("relay parameters must be a dataclass or frozen Pydantic model")
        relay_id = getattr(params, "relay_id", None)
        if not relay_id:
            return params

        with self._session_factory() as db, db.begin():
            # Locked, so an activation cannot commit between reading the
            # active key and signing: a grant signed by a key retired after
            # the read, for a lease allocated after that retirement, would
            # outlive the retired key's reported validity. SQLite ignores the
            # lock, but its writers are serialized, so there the signing's own
            # write fails instead and the job's retry signs with the new key.
            relay = db.get(Relay, relay_id, with_for_update=True)
            if relay is None:
                raise RelayUnusableAtExecutionError(
                    f"job references relay '{relay_id}', which no longer exists; "
                    "the delivery would have no external route"
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
            encryption_key = str(getattr(self._settings, "ssh_decryption_key", "") or "")
            fields: dict[str, Any] = {
                "relay_addr": relay.relay_addr,
                "relay_port": relay.relay_port,
                "relay_token": decrypt_secret(relay.relay_token_encrypted, encryption_key),
            }
            if remote_port is not None:
                fields["relay_grant"] = self._signed_grant(
                    db, relay, int(remote_port), owner_id, encryption_key
                )
            if isinstance(params, BaseModel):
                if not fields.keys() <= type(params).model_fields.keys():
                    raise TypeError("relay parameters do not declare the resolved fields")
                return params.model_copy(update=fields)
            return replace(params, **fields)

    @staticmethod
    def _signed_grant(
        db: Any, relay: Relay, remote_port: int, owner_id: str | None, encryption_key: str
    ) -> str:
        """The grant for the job's own held lease of ``remote_port``, signed now.

        Refused as unusable, like a relay with no token, when the relay holds
        no active key: a proxy registered without a grant is refused by a
        relay enforcing admission. Refused too when the port's held lease is
        not the job's reservation's, or the job names none: a grant authorizes
        its port alone, so one signed for another tenancy's lease would let
        this job's proxy take a port another buyer holds.
        """
        if not relay.grant_key_encrypted:
            raise RelayUnusableAtExecutionError(
                f"relay '{relay.id}' has no active grant key, so the proxy's "
                "grant cannot be signed and the relay would refuse it"
            )
        lease = (
            db.query(RelayPortLease)
            .filter(
                RelayPortLease.relay_id == relay.id,
                RelayPortLease.remote_port == remote_port,
                RelayPortLease.released_at.is_(None),
            )
            .one_or_none()
        )
        if lease is None or owner_id is None or lease.owner_id != owner_id:
            raise RelayUnusableAtExecutionError(
                f"relay '{relay.id}' holds no lease on port {remote_port} for this "
                "job's reservation, so no grant can be signed for its proxy"
            )
        key = GrantKey.from_profile_form(
            decrypt_secret(relay.grant_key_encrypted, encryption_key)
        )
        try:
            grant = sign_grant(lease, key)
        except ValueError as exc:
            raise RelayUnusableAtExecutionError(str(exc)) from exc
        lease.grant_key_id = key.kid
        return grant


__all__ = ["RelayExecutionResolver", "RelayUnusableAtExecutionError"]
