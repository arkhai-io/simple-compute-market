"""The relay tables: relays, the ports leased on them, and each pool's relay.

They are the compute family's: a relay is a rendezvous any family host dials,
and every domain whose deliveries reach their buyer through one leases its
ports from the same window. The provisioning service holds them in its
database beside every other capability's tables: its schema creation creates
this metadata, and its migration history reads these models to create and
evolve them.
"""

from market_resource_pools import ResourcePool
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.sql import func
from sqlalchemy.sql.expression import true as sa_true

Base = declarative_base()


class Relay(Base):
    """A buyer-facing tunnel rendezvous, and the remote-port window it accepts.

    **This is not the host management tunnel.** A host holds two reverse
    tunnels and they are easy to confuse, so: the management tunnel is the
    operator's failsafe path to the host itself, static for a whole
    provisioning service, established when the host is prepared outside this
    repository, and absent from this table. What a row here describes is the
    rendezvous a host's buyer-facing tunnel client dials on behalf of the
    deliveries made on it. The two may be the same server; they are never the
    same concern, and nothing in this service writes or restarts the
    management side.

    One row per rendezvous. ``UNIQUE(relay_addr, relay_port)`` is what makes
    identity trustworthy: a remote port binds a listening socket on the relay
    itself, so one rendezvous recorded twice would issue the same port to two
    callers and the refusal would surface asynchronously in a tunnel client's
    log rather than as a failed allocation.

    The admission token and the grant-signing private keys are stored
    encrypted under the deployment's ``ssh_decryption_key``, the same key that
    protects embedded host key material. The database therefore holds no
    usable credential: recovering one requires both this row and a key held
    outside the database. No read path that serves an API response, an export,
    or a reconciliation comparison may return either — the pool configuration
    handlers expose a redacted read under the unqualified name and secrets only
    through an explicitly named execution read.
    """

    __tablename__ = "relays"
    __table_args__ = (
        UniqueConstraint("relay_addr", "relay_port", name="uq_relays_endpoint"),
    )

    id = Column(String, primary_key=True)
    label = Column(String, nullable=True)
    relay_addr = Column(String, nullable=False)
    relay_port = Column(Integer, nullable=False)
    vm_port_range_start = Column(Integer, nullable=False)
    vm_port_range_count = Column(Integer, nullable=False)
    # Ciphertext, or NULL when no token has been supplied yet. A relay with no
    # token is rejected before dispatch rather than dialled and refused.
    relay_token_encrypted = Column(String, nullable=True)
    # The relay's active grant-signing key: the private key in its profile
    # form, encrypted as the token is; its id (the thumbprint the admission
    # plugin derives); its public half, kept so a read never decrypts a private
    # key; and when it became active. NULL while the relay holds no active key,
    # which fulfillment preparation refuses: a proxy without a grant would be
    # refused by a relay enforcing admission.
    grant_key_encrypted = Column(String, nullable=True)
    grant_key_id = Column(String, nullable=True)
    grant_key_public = Column(String, nullable=True)
    grant_key_activated_at = Column(DateTime, nullable=True)
    # A key staged for rotation: returned to the operator to configure on the
    # relay's plugin before it is activated.
    staged_grant_key_encrypted = Column(String, nullable=True)
    staged_grant_key_id = Column(String, nullable=True)
    staged_grant_key_public = Column(String, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default=sa_true())
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=True, onupdate=func.now())

    @staticmethod
    def normalize_addr(addr: str) -> str:
        """Canonical spelling of a rendezvous address.

        Applied on write so two spellings of one endpoint collide on the
        unique constraint instead of creating two rows that would each issue
        ports the other already holds.
        """
        return addr.strip().lower()


class RelayPortLease(Base):
    """A remote port held on a relay for one delivery.

    Uniqueness is ``(relay_id, remote_port)`` because that is the resource: a
    ``tcp`` proxy's remote port binds a listening socket on the relay itself.
    Hosts sharing a relay share one port namespace, and so do pools; keying on
    either would issue a port already bound, and the relay's refusal surfaces
    asynchronously in a tunnel client's log rather than as a failed allocation.

    The relay recorded here is the delivery's relay for the whole of its life.
    Teardown and reclamation read it rather than the pool's current
    configuration, which may since have been rebound: the lease is what knows
    where the port actually went, and releasing against anything else frees a
    port that was never bound and leaves bound the one that was.

    A lease is recorded before the job that will use it is dispatched, so a
    crash between the two cannot leave a port bound on the relay that no record
    claims. It is released with its reservation's capacity, whatever releases
    it: a torn-down delivery's lease release, an abandoned dispatch, a lapsed
    hold, or an operator's forced release after verifying a host whose creation
    failed. A failed creation alone releases nothing, because it may have left
    a proxy running. Reconciliation bounds whatever path is missed.
    """

    __tablename__ = "relay_port_leases"
    __table_args__ = (
        UniqueConstraint("relay_id", "remote_port", name="uq_relay_port_leases_endpoint"),
        # One active lease per owner, enforced rather than only queried, so two
        # concurrent retries of one fulfillment cannot both take a port. Partial
        # because release is soft: a released lease keeps its row, and an
        # unconditional constraint would stop an owner ever holding a second
        # lease across its history. SQLite (3.8+) and PostgreSQL both support it.
        Index(
            "uq_relay_port_leases_active_owner",
            "owner_kind",
            "owner_id",
            unique=True,
            sqlite_where=text("released_at IS NULL"),
            postgresql_where=text("released_at IS NULL"),
        ),
    )

    id = Column(String, primary_key=True)
    # References the relay row rather than a string assembled from its address,
    # so a relay moving to a new address updates one field and its leases
    # follow it instead of becoming records under an identity nothing points at.
    relay_id = Column(String, ForeignKey("relays.id"), nullable=False, index=True)
    remote_port = Column(Integer, nullable=False)
    # Recorded for operator visibility and reconciliation, not for uniqueness.
    host_id = Column(String, nullable=True)
    pool_id = Column(String, nullable=True)
    # The reservation whose released capacity releases this lease.
    owner_kind = Column(String, nullable=False)
    owner_id = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    released_at = Column(DateTime, nullable=True)
    # When the grants for this tenancy expire: the reservation's lease end plus
    # the configured grace, rounded up to the whole second, in UTC with no zone
    # as the table's other times are. Fixed at allocation, so every grant a
    # job's retries sign carries one expiry, and the port is not reissued until
    # it plus the reuse margin has passed. NULL only on a lease allocated
    # before grants existed.
    grant_expires_at = Column(DateTime, nullable=True)
    # The key that signed this lease's latest grant: a diagnostic the holdings
    # read reports. A retired key's validity is bounded from the leases, not
    # from this, since a retried job may have installed grants from two keys.
    grant_key_id = Column(String, nullable=True)


class RelayRetiredGrantKey(Base):
    """A grant-signing key a relay held before its active one.

    Only the id and the retirement time are kept: a retired key is never
    active again, and the operator removes it from the relay's plugin by the
    thumbprint the plugin prints for it.
    """

    __tablename__ = "relay_retired_grant_keys"

    relay_id = Column(String, ForeignKey("relays.id"), primary_key=True)
    key_id = Column(String, primary_key=True)
    retired_at = Column(DateTime, nullable=False)


class PoolRelay(Base):
    """Which relay a pool's hosts dial for buyer tunnels, whatever its provider.

    One row per pool that references a relay; a pool with no row reaches its
    buyers without one. A reference, not the endpoint: the rendezvous address,
    its port window, and its token belong to the relay row, shared by every
    pool pointing at it. Held in one table rather than in each provider's
    configuration so "which relay does this pool use" and "which pools use this
    relay" are one query each, and the rebinding rule has one place to read.

    No ORM ``relationship()`` to ``ResourcePool``: that model lives in another
    declarative registry, so navigation is by explicit ``pool_id``.
    """

    __tablename__ = "pool_relays"

    pool_id = Column(String, ForeignKey(ResourcePool.__table__.c.id), primary_key=True)
    relay_id = Column(String, ForeignKey("relays.id"), nullable=False, index=True)


__all__ = ["Base", "PoolRelay", "Relay", "RelayPortLease", "RelayRetiredGrantKey"]
