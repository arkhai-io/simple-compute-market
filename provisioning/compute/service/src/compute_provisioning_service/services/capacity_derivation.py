"""Capacity declarations derived from legacy host capacity.

A host record carries ``gpu_count`` and ``gpu_model`` from INI inventory, but a
host is connection identity: what a site sells is declared by capacity
resources. A host whose legacy data would otherwise sell nothing gets a
declaration derived from it, where that data enters the service: when INI
inventory is applied, and once for the hosts present at upgrade.

A derived declaration is::

    resource_id    the host's host_id
    host_id        the host's host_id
    pool_id        the host's pool_id
    resource_type  compute.gpu
    capacity       {"gpu_count": host.gpu_count}
    attributes     {"gpu_model": host.gpu_model} when recorded, otherwise {}
    enabled        the host's enabled

Derivation only adds. A host is derived only when it has GPUs and no
declaration names it. A host whose ``host_id`` is already some other
declaration's ``resource_id`` is skipped rather than overwriting it. Once any
declaration names a host, its later INI values have no effect on capacity.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass

from market_site import CapacityDeclaration, CapacityLedgerService
from market_site.db import CapacityBucket
from sqlalchemy.orm import Session

from compute_provisioning_service.db.models import Host

logger = logging.getLogger(__name__)

DERIVED_RESOURCE_TYPE = "compute.gpu"
DERIVED_DIMENSION = "gpu_count"


@dataclass(frozen=True)
class LegacyHostCapacity:
    """The host facts a derivation reads."""

    host_id: str
    pool_id: str
    gpu_count: int
    gpu_model: str | None
    enabled: bool


@dataclass(frozen=True)
class DerivationPlan:
    """Declarations to register, and hosts skipped with the reason."""

    declarations: tuple[CapacityDeclaration, ...]
    skipped: tuple[tuple[str, str], ...]


def plan_derived_declarations(
    hosts: Iterable[LegacyHostCapacity],
    *,
    declared_host_ids: set[str],
    existing_resource_ids: set[str],
) -> DerivationPlan:
    """Decide which hosts get a derived declaration. Reads and writes nothing.

    A host with no GPUs is not derived: it has no legacy capacity to
    preserve, and a zero declaration would publish a resource with nothing
    to sell. A host some declaration already names is not derived, whatever
    that declaration says. A host whose id another declaration already uses
    as its resource id is skipped and reported, because registering it would
    replace that declaration.
    """
    declarations: list[CapacityDeclaration] = []
    skipped: list[tuple[str, str]] = []
    for host in hosts:
        if host.gpu_count <= 0 or host.host_id in declared_host_ids:
            continue
        if host.host_id in existing_resource_ids:
            skipped.append(
                (
                    host.host_id,
                    f"a declaration already uses resource id {host.host_id!r} "
                    "without naming this host",
                )
            )
            continue
        declarations.append(
            CapacityDeclaration(
                resource_id=host.host_id,
                host_id=host.host_id,
                pool_id=host.pool_id,
                resource_type=DERIVED_RESOURCE_TYPE,
                capacity={DERIVED_DIMENSION: host.gpu_count},
                attributes={"gpu_model": host.gpu_model} if host.gpu_model else {},
                enabled=host.enabled,
            )
        )
    return DerivationPlan(tuple(declarations), tuple(skipped))


class LegacyHostCapacityDerivation:
    """Derives declarations inside the caller's session and transaction.

    Supplied to host inventory as its capacity-derivation port, so a host
    applied from INI and its derived declaration commit together.
    """

    def __init__(self, ledger: CapacityLedgerService) -> None:
        self._ledger = ledger

    def serialized(self) -> AbstractContextManager[None]:
        """The ledger's serialization lock, for the caller to hold around its
        whole transaction."""
        return self._ledger.serialized()

    def derive_in_session(
        self, db: Session, host_ids: Sequence[str] | None = None
    ) -> list[str]:
        """Derive for ``host_ids``, or for every host when ``None``.

        Returns the resource ids declared. Neither opens a session nor
        commits; the caller holds :meth:`serialized` around the transaction. The caller's pending writes are flushed first, so hosts it
        upserted in this transaction are what the derivation reads, whether
        or not its session autoflushes.
        """
        db.flush()
        query = db.query(Host)
        if host_ids is not None:
            if not host_ids:
                return []
            query = query.filter(Host.host_id.in_(list(host_ids)))
        hosts = [
            LegacyHostCapacity(
                host_id=row.host_id,
                pool_id=row.pool_id,
                gpu_count=int(row.gpu_count or 0),
                gpu_model=row.gpu_model,
                enabled=bool(row.enabled),
            )
            for row in query.order_by(Host.host_id).all()
        ]
        declared = {
            host_id
            for (host_id,) in db.query(CapacityBucket.host_id).filter(
                CapacityBucket.host_id.isnot(None)
            )
        }
        resource_ids = {
            resource_id
            for (resource_id,) in db.query(CapacityBucket.backing_resource_id)
        }
        plan = plan_derived_declarations(
            hosts, declared_host_ids=declared, existing_resource_ids=resource_ids
        )
        for host_id, reason in plan.skipped:
            logger.warning(
                "Capacity derivation: host %s not derived: %s", host_id, reason
            )
        derived = []
        for declaration in plan.declarations:
            self._ledger.register_declaration_in_session(db, declaration)
            derived.append(declaration.resource_id)
        if derived:
            logger.info(
                "Capacity derivation: declared %d resource(s) from legacy host "
                "capacity: %s",
                len(derived),
                ", ".join(derived),
            )
        return derived
